import logging
import requests
from .base import Vehicle

logger = logging.getLogger(__name__)

# --- Home Assistant Client ---
class HomeAssistantClient:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def get_state(self, entity_id):
        url = f"{self.base_url}/api/states/{entity_id}"
        # logger.info(f"HA: Fetching state for {entity_id} from {url}")
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"HA: Error fetching state for {entity_id} from HA: {e}")
            return None

    def call_service(self, domain, service, entity_id):
        url = f"{self.base_url}/api/services/{domain}/{service}"
        payload = {"entity_id": entity_id}
        logger.info(f"HA: Calling service {domain}.{service} for {entity_id}")
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=10)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"HA: Error calling service {domain}.{service}: {e}")
            return False

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
            "climate_active": False
        }

        if not self.ha_client:
            return status

        # SoC
        if self.config.get('ha_merc_soc_entity_id'):
            state = self.ha_client.get_state(self.config['ha_merc_soc_entity_id'])
            if state and 'state' in state:
                try:
                    status['soc'] = int(float(state['state']))
                except ValueError:
                    pass

        # Plugged In
        plug_id = self.config.get('ha_merc_plugged_entity_id')
        if plug_id:
            state = self.ha_client.get_state(plug_id)
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

        # Climate
        climate_id = self.config.get('climate_status_id')
        if climate_id:
            state = self.ha_client.get_state(climate_id)
            if state and str(state.get('state')).lower() in ['on', 'true', '1', 'active']:
                status['climate_active'] = True

        logger.info(f"MercedesEQV Status: {status}")
        return status

    def start_climate(self):
        cid = self.config.get('climate_entity_id')
        if self.ha_client and cid:
            domain = cid.split('.')[0]
            service = "press" if domain == "button" else "turn_on"
            return self.ha_client.call_service(domain, service, cid)
        return False

    def stop_climate(self):
        cid = self.config.get('climate_entity_id')
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
            "climate_active": False
        }

        if not self.ha_client:
            return status

        # SoC
        if self.config.get('ha_nissan_soc_entity_id'):
            state = self.ha_client.get_state(self.config['ha_nissan_soc_entity_id'])
            if state and 'state' in state:
                try:
                    status['soc'] = int(float(state['state']))
                except ValueError:
                    pass

        # Plugged In
        plug_id = self.config.get('ha_nissan_plugged_entity_id')
        if plug_id:
            state = self.ha_client.get_state(plug_id)
            if state and state.get('state') == 'on':
                status['plugged_in'] = True

        # Range
        range_id = self.config.get('ha_nissan_range_entity_id')
        if range_id:
            state = self.ha_client.get_state(range_id)
            if state and 'state' in state:
                try:
                    status['range_km'] = int(float(state['state']))
                except ValueError:
                    pass

        # Climate
        climate_id = self.config.get('climate_entity_id')
        if climate_id:
            state = self.ha_client.get_state(climate_id)
            if state and str(state.get('state')).lower() in ['on', 'true', '1', 'active']:
                status['climate_active'] = True

        logger.info(f"NissanLeaf Status: {status}")
        return status

    def start_climate(self):
        cid = self.config.get('climate_entity_id')
        if self.ha_client and cid:
            return self.ha_client.call_service("switch", "turn_on", cid)
        return False

    def stop_climate(self):
        cid = self.config.get('climate_entity_id')
        if self.ha_client and cid:
            return self.ha_client.call_service("switch", "turn_off", cid)
        return False

    def wake_up(self):
        # Use hardcoded default if not in config, as we discovered it via find_ha_entities.py
        update_id = self.config.get('update_entity_id', "button.leaf_update_data")
        if self.ha_client and update_id:
            logger.info(f"NissanLeaf: Sending wake_up/update command to {update_id}")
            return self.ha_client.call_service("button", "press", update_id)
        return False
