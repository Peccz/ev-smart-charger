import logging
from datetime import datetime, timedelta, timezone
from .base import Vehicle
from .home_assistant import HomeAssistantClient

logger = logging.getLogger(__name__)

class MercedesEQV(Vehicle):
    def __init__(self, config):
        super().__init__(config)
        self.name = "Mercedes EQV"
        self.capacity_kwh = config.get('capacity_kwh', 90)
        self.max_charge_kw = config.get('max_charge_kw', 11)

        self.ha_client = None
        if self.config.get('ha_url') and self.config.get('ha_token'):
            self.ha_client = HomeAssistantClient(self.config['ha_url'], self.config['ha_token'])
            logger.info("MercedesEQV: HA client initialized.")

        self.ha_merc_soc_entity_id = config.get('ha_merc_soc_entity_id')
        self.ha_merc_plugged_entity_id = config.get('ha_merc_plugged_entity_id')
        self.ha_climate_id = config.get('climate_entity_id')
        self.ha_climate_status_id = config.get('climate_status_id')
        self.ha_odometer_id = config.get('odometer_entity_id')

    def start_charging(self):
        """
        Mercedes Me HA integration does not support remote charging control.
        Use Zaptec charger control instead.
        """
        logger.info("MercedesEQV: start_charging() called - Mercedes Me does not support remote start")
        logger.info("MercedesEQV: Use ZaptecCharger.start_charging() to control charging")
        return False

    def stop_charging(self):
        """
        Mercedes Me HA integration does not support remote charging control.
        Use Zaptec charger control instead.
        """
        logger.info("MercedesEQV: stop_charging() called - Mercedes Me does not support remote stop")
        logger.info("MercedesEQV: Use ZaptecCharger.stop_charging() to control charging")
        return False

    def validate_config(self):
        required = ['ha_url', 'ha_token', 'ha_merc_soc_entity_id']
        missing = [key for key in required if not self.config.get(key)]
        if missing:
            logger.warning(f"MercedesEQV: Missing config for HA integration: {missing}")

    def get_status(self):
        # Default "Empty" status
        status = {
            "soc": 0,
            "range_km": 0,
            "plugged_in": False,
            "odometer": 0,
            "climate_active": False,
            "is_home": True # Default assumption
        }
        
        # Debug log to verify IDs
        # logger.info(f"DEBUG: Odometer ID={self.ha_odometer_id}, Plugged ID={self.ha_merc_plugged_entity_id}")

        if not self.ha_client:
            return status

        # SoC
        if self.ha_merc_soc_entity_id:
            state = self.ha_client.get_state(self.ha_merc_soc_entity_id)
            if state and 'state' in state:
                try:
                    status['soc'] = int(float(state['state']))
                except ValueError:
                    pass

        # Plugged In
        if self.ha_merc_plugged_entity_id:
            state = self.ha_client.get_state(self.ha_merc_plugged_entity_id)
            if state and 'attributes' in state:
                attrs = state['attributes']
                # Specific logic for Mercedes sensor attributes
                if attrs.get('chargingactive', False):
                    status['plugged_in'] = True
                elif 'chargingstatus' in attrs:
                    val = str(attrs['chargingstatus']).lower()
                    if val not in ['3', 'disconnected', 'null', 'off', 'unavailable', 'unknown']:
                        status['plugged_in'] = True
        
        # Range
        # Note: hardcoded override for range sensor based on previous findings, or use config
        range_id = "sensor.urg48t_range_electric" 
        if range_id:
            state = self.ha_client.get_state(range_id)
            if state and 'state' in state:
                try:
                    status['range_km'] = int(float(state['state']))
                except ValueError:
                    pass

        # Odometer
        if self.ha_odometer_id:
            state = self.ha_client.get_state(self.ha_odometer_id)
            if state and 'state' in state:
                try:
                    status['odometer'] = int(float(state['state']))
                except ValueError:
                    pass

        # Climate
        if self.ha_climate_status_id:
            state = self.ha_client.get_state(self.ha_climate_status_id)
            if state and str(state.get('state')).lower() in ['on', 'true', '1', 'active']:
                status['climate_active'] = True

        logger.info(f"MercedesEQV Status: {status}")
        return status

    def start_climate(self):
        cid = self.ha_climate_id
        if self.ha_client and cid:
            domain = cid.split('.')[0]
            service = "press" if domain == "button" else "turn_on"
            return self.ha_client.call_service(domain, service, cid)
        return False

    def stop_climate(self):
        cid = self.ha_climate_id
        if self.ha_client and cid:
            if "start" in cid:
                stop_id = cid.replace("start", "stop")
                return self.ha_client.call_service("button", "press", stop_id)
            return self.ha_client.call_service("switch", "turn_off", cid)
        return False

class NissanLeaf(Vehicle):
    def __init__(self, config):
        super().__init__(config)
        self.name = "Nissan Leaf"
        self.capacity_kwh = config.get('capacity_kwh', 40)
        self.max_charge_kw = config.get('max_charge_kw', 3.7) # 1-phase 16A default

        self.ha_client = None
        if self.config.get('ha_url') and self.config.get('ha_token'):
            self.ha_client = HomeAssistantClient(self.config['ha_url'], self.config['ha_token'])
            logger.info("NissanLeaf: HA client initialized.")
            
        self.ha_nissan_soc_entity_id = config.get('ha_nissan_soc_entity_id')
        self.ha_nissan_plugged_entity_id = config.get('ha_nissan_plugged_entity_id')
        self.ha_nissan_range_entity_id = config.get('ha_nissan_range_entity_id')
        self.ha_nissan_last_updated_id = config.get('ha_nissan_last_updated_id')
        self.ha_climate_id = config.get('climate_entity_id')
        self.ha_odometer_id = config.get('odometer_entity_id')
        self.ha_location_id = config.get('location_id')
        self.ha_update_id = config.get('update_entity_id')
        self.ha_nissan_charging_entity_id = config.get('ha_nissan_charging_entity_id') # New entity for charging status
        
        # State for automatic wakeup
        self._last_wakeup_time = datetime.min.replace(tzinfo=timezone.utc)

    def validate_config(self):
        required = ['ha_url', 'ha_token', 'ha_nissan_soc_entity_id']
        missing = [key for key in required if not self.config.get(key)]
        if missing:
            logger.warning(f"NissanLeaf: Missing config for HA integration: {missing}")

    def get_status(self):
        status = {
            "soc": 0,
            "range_km": 0,
            "plugged_in": False,
            "odometer": 0,
            "climate_active": False,
            "is_charging": False, # New field for car's charging status
            "is_home": True 
        }

        if not self.ha_client:
            return status

        # SoC
        if self.ha_nissan_soc_entity_id:
            state = self.ha_client.get_state(self.ha_nissan_soc_entity_id)
            if state and 'state' in state:
                try:
                    status['soc'] = int(float(state['state']))
                except ValueError:
                    pass

        # Plugged In
        if self.ha_nissan_plugged_entity_id:
            state = self.ha_client.get_state(self.ha_nissan_plugged_entity_id)
            if state and state.get('state') == 'on':
                status['plugged_in'] = True

        # Car's internal charging status
        if self.ha_nissan_charging_entity_id:
            state = self.ha_client.get_state(self.ha_nissan_charging_entity_id)
            if state and state.get('state') == 'on':
                status['is_charging'] = True

        # Range
        if self.ha_nissan_range_entity_id:
            state = self.ha_client.get_state(self.ha_nissan_range_entity_id)
            if state and 'state' in state:
                try:
                    status['range_km'] = int(float(state['state']))
                except ValueError:
                    pass
        
        # Odometer
        if self.ha_odometer_id:
            state = self.ha_client.get_state(self.ha_odometer_id)
            if state and 'state' in state:
                try:
                    status['odometer'] = int(float(state['state']))
                except ValueError:
                    pass

        # Climate
        if self.ha_climate_id:
            state = self.ha_client.get_state(self.ha_climate_id)
            if state and str(state.get('state')).lower() in ['on', 'true', '1', 'active']:
                status['climate_active'] = True
        
        # Location Check (Geofence)
        if self.ha_location_id:
            loc = self.ha_client.get_state(self.ha_location_id)
            if loc and loc.get('state') != 'home':
                # logger.info(f"NissanLeaf: Location is '{loc.get('state')}' (Not Home). Forcing plugged_in=False.")
                status['plugged_in'] = False
                status['is_home'] = False
            else:
                status['is_home'] = True

        # Check staleness and wake up if needed
        if self.ha_nissan_last_updated_id:
            lu_state = self.ha_client.get_state(self.ha_nissan_last_updated_id)
            if lu_state and 'state' in lu_state and lu_state['state'] not in ['unknown', 'unavailable']:
                try:
                    # Parse ISO format (e.g. 2025-12-08T11:10:42+00:00)
                    last_updated = datetime.fromisoformat(lu_state['state'])
                    now = datetime.now(timezone.utc)
                    age = now - last_updated
                    
                    # If data is older than 4 hours, try to wake up
                    # (with 60 min cooldown)
                    if age > timedelta(hours=4):
                        if (now - self._last_wakeup_time) > timedelta(minutes=60):
                            logger.info(f"NissanLeaf: Data is old ({age}). Triggering wake_up...")
                            self.wake_up()
                            self._last_wakeup_time = now
                except Exception as e:
                    logger.warning(f"NissanLeaf: Failed to check staleness: {e}")

        logger.info(f"NissanLeaf Status: {status}")
        return status

    def start_charging(self):
        """
        Start charging via HomeAssistant button.leaf_start_charge.
        Note: This sends a start command to the car itself. For best results,
              use ZaptecCharger.start_charging() which controls the charger directly.
        """
        if not self.ha_client:
            logger.error("NissanLeaf: Cannot start charging - HA client not initialized")
            return False

        entity_id = "button.leaf_start_charge"
        logger.info(f"NissanLeaf: Starting charging via {entity_id}")
        logger.info(f"NissanLeaf: This tells the CAR to start. For charger control, use ZaptecCharger.start_charging()")
        return self.ha_client.call_service("button", "press", entity_id)

    def stop_charging(self):
        """
        Nissan Leaf HA integration does not have a stop charging button.
        Use Zaptec charger control instead.
        """
        logger.info("NissanLeaf: stop_charging() called - Nissan integration does not support remote stop")
        logger.info("NissanLeaf: Use ZaptecCharger.stop_charging() to control charging")
        return False

    def start_climate(self):
        if self.ha_client and self.ha_climate_id:
            # Check if it's a switch or climate entity
            domain = self.ha_climate_id.split('.')[0]
            if domain == "climate":
                return self.ha_client.call_service("climate", "set_hvac_mode", self.ha_climate_id, hvac_mode="heat_cool")
            return self.ha_client.call_service("switch", "turn_on", self.ha_climate_id)
        return False

    def stop_climate(self):
        if self.ha_client and self.ha_climate_id:
            domain = self.ha_climate_id.split('.')[0]
            if domain == "climate":
                return self.ha_client.call_service("climate", "set_hvac_mode", self.ha_climate_id, hvac_mode="off")
            return self.ha_client.call_service("switch", "turn_off", self.ha_climate_id)
        return False

    def wake_up(self):
        if self.ha_client and self.ha_update_id:
            logger.info(f"NissanLeaf: Sending wake_up/update command to {self.ha_update_id}")
            return self.ha_client.call_service("button", "press", self.ha_update_id)
        return False