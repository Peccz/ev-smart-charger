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

        self.ha_soc_id = config.get('ha_soc_id')
        self.ha_plugged_id = config.get('ha_plugged_id')
        self.ha_climate_id = config.get('climate_entity_id')
        self.ha_climate_status_id = config.get('climate_status_id')
        self.ha_odometer_id = config.get('odometer_entity_id')
        self.ha_location_id = config.get('location_id')

    def start_charging(self):
        logger.info("MercedesEQV: start_charging() called - Mercedes Me does not support remote start")
        return False

    def stop_charging(self):
        logger.info("MercedesEQV: stop_charging() called - Mercedes Me does not support remote stop")
        return False

    def validate_config(self):
        required = ['ha_url', 'ha_token', 'ha_soc_id']
        missing = [key for key in required if not self.config.get(key)]
        if missing:
            logger.warning(f"MercedesEQV: Missing config for HA integration: {missing}")

    def get_status(self):
        status = {
            "soc": 0,
            "range_km": 0,
            "plugged_in": False,
            "odometer": 0,
            "climate_active": False,
            "is_home": True,
            "is_charging": False
        }
        
        if not self.ha_client:
            return status

        # SoC
        if self.ha_soc_id:
            state = self.ha_client.get_state(self.ha_soc_id)
            if state and 'state' in state:
                try: status['soc'] = int(float(state['state']))
                except: pass

        # Plugged In & Charging
        if self.ha_plugged_id:
            state_obj = self.ha_client.get_state(self.ha_plugged_id)
            if state_obj:
                state_val = str(state_obj.get('state', '')).lower()
                attrs = state_obj.get('attributes', {})
                
                if state_val in ['0', '1', '2', '4', 'charging', 'complete', 'on_hold']:
                    status['plugged_in'] = True
                    if state_val in ['0', 'charging']:
                        status['is_charging'] = True
                elif attrs.get('chargingactive', False):
                    status['plugged_in'] = True
                    status['is_charging'] = True
        
        # Odometer
        if self.ha_odometer_id:
            state = self.ha_client.get_state(self.ha_odometer_id)
            if state and 'state' in state:
                try: status['odometer'] = int(float(state['state']))
                except: pass

        # Location Check
        if self.ha_location_id:
            loc = self.ha_client.get_state(self.ha_location_id)
            if loc and 'state' in loc and loc.get('state') not in ['home', 'unknown', 'unavailable']:
                status['plugged_in'] = False
                status['is_home'] = False
            elif not loc:
                # Entity defined but not found (e.g. 404)
                status['is_home'] = True 
        else:
            status['is_home'] = True

        status['climate_active'] = self._get_climate_active()
        logger.info(f"MercedesEQV Status: {status}")
        return status

    def _get_climate_active(self):
        if self.ha_climate_status_id:
            state = self.ha_client.get_state(self.ha_climate_status_id)
            if state and str(state.get('state')).lower() in ['on', 'true', '1', 'active']:
                return True
        return False

    def start_climate(self):
        if self.ha_client and self.ha_climate_id:
            domain = self.ha_climate_id.split('.')[0]
            service = "press" if domain == "button" else "turn_on"
            return self.ha_client.call_service(domain, service, self.ha_climate_id)
        return False

    def stop_climate(self):
        if self.ha_client and self.ha_climate_id:
            if "start" in self.ha_climate_id:
                stop_id = self.ha_climate_id.replace("start", "stop")
                return self.ha_client.call_service("button", "press", stop_id)
            return self.ha_client.call_service("switch", "turn_off", self.ha_climate_id)
        return False
