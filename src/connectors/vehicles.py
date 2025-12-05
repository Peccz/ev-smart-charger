from abc import ABC, abstractmethod
import logging
# Removed pycarwings2 as it's not working reliably
# Removed kamereon_python as it's not working reliably
import requests

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
        logger.info(f"HA: Fetching state for {entity_id} from {url}")
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"HA: Error fetching state for {entity_id} from HA: {e}")
            return None
            
# --- Vehicle Classes ---

class Vehicle(ABC):
    def __init__(self, name, capacity_kwh, max_charge_kw):
        self.name = name
        self.capacity_kwh = capacity_kwh
        self.max_charge_kw = max_charge_kw
        logger.info(f"Vehicle: Initializing {name} with capacity={capacity_kwh} kWh, max_charge={max_charge_kw} kW")


    @abstractmethod
    def get_soc(self):
        """Returns State of Charge (0-100)"""
        pass

    @abstractmethod
    def get_status(self):
        """Returns dict with soc, range, plugged_in status"""
        pass

class MercedesEQV(Vehicle):
    def __init__(self, config):
        logger.info(f"MercedesEQV: Initializing with config: {config}")
        # Ensure these keys exist before passing to super()
        super().__init__("Mercedes EQV", 
                         config.get('capacity_kwh', 90), 
                         config.get('max_charge_kw', 11))
        self.vin = config.get('vin')
        # Home Assistant Config
        self.ha_url = config.get('ha_url')
        self.ha_token = config.get('ha_token')
        self.ha_merc_soc_entity_id = config.get('ha_merc_soc_entity_id')
        
        self.ha_client = None
        if self.ha_url and self.ha_token:
            self.ha_client = HomeAssistantClient(self.ha_url, self.ha_token)
            logger.info("MercedesEQV: HA client initialized.")
        else:
            logger.warning("MercedesEQV: HA credentials incomplete. Will use fallback.")


    def get_status(self):
        logger.info("MercedesEQV: Attempting to get status from HA.")
        # 1. Try Home Assistant API
        if self.ha_client and self.ha_merc_soc_entity_id:
            state = self.ha_client.get_state(self.ha_merc_soc_entity_id)
            if state and 'state' in state:
                try:
                    soc = float(state['state'])
                    plugged_in = False # Default assumption
                    # Look for common HA attributes for charging/plugged_in status
                    if state.get('attributes', {}).get('charging', False) or \
                       state.get('attributes', {}).get('pluggedIn', False) or \
                       state.get('attributes', {}).get('charge_port_door_closed', False) : # Some integrations use this
                        plugged_in = True
                    logger.info(f"MercedesEQV: HA data parsed: SoC={soc}%, Plugged={plugged_in}")
                    return {
                        "vehicle": self.name,
                        "soc": int(soc),
                        "range_km": int(state.get('attributes', {}).get('range', 0)),
                        "plugged_in": plugged_in
                    }
                except ValueError:
                    logger.error(f"MercedesEQV: HA SoC state is not a number: {state['state']}. Using fallback.")
        
        # 2. Fallback to Mock/Manual
        logger.warning("MercedesEQV: HA integration not fully configured or failed. Using fallback mock data.")
        return {
            "vehicle": self.name,
            "soc": 0, # Fallback mock to clearly show failure
            "range_km": 0,
            "plugged_in": False # Fallback mock
        }

    def get_soc(self):
        s = self.get_status()
        return s.get('soc', 0)

class NissanLeaf(Vehicle):
    def __init__(self, config):
        logger.info(f"NissanLeaf: Initializing with config: {config}")
        super().__init__("Nissan Leaf",
                         config.get('capacity_kwh', 40),
                         config.get('max_charge_kw', 6.6))
        self.vin = config.get('vin')
        # Home Assistant Config
        self.ha_url = config.get('ha_url')
        self.ha_token = config.get('ha_token')
        self.ha_nissan_soc_entity_id = config.get('ha_nissan_soc_entity_id')
        self.ha_nissan_plugged_entity_id = config.get('ha_nissan_plugged_entity_id')
        self.ha_nissan_range_entity_id = config.get('ha_nissan_range_entity_id')

        # Debug Logging for Configuration
        token_masked = "***" if self.ha_token else "None"
        logger.info(f"NissanLeaf Config Check: URL={self.ha_url}, Token={token_masked}, "
                    f"SoC_ID={self.ha_nissan_soc_entity_id}, "
                    f"Plugged_ID={self.ha_nissan_plugged_entity_id}")

        self.ha_client = None
        if self.ha_url and self.ha_token:
            self.ha_client = HomeAssistantClient(self.ha_url, self.ha_token)
            logger.info("NissanLeaf: HA client initialized successfully.")
        else:
            logger.warning(f"NissanLeaf: HA credentials incomplete (URL or Token missing). Client NOT created.")

    def get_status(self):
        logger.info("NissanLeaf: Attempting to get status from HA.")
        # Try Home Assistant API
        if self.ha_client and self.ha_nissan_soc_entity_id:
            state = self.ha_client.get_state(self.ha_nissan_soc_entity_id)
            if state and 'state' in state:
                try:
                    soc = float(state['state'])

                    # Get plugged_in status from separate sensor if available
                    plugged_in = False
                    if self.ha_nissan_plugged_entity_id:
                        plugged_state = self.ha_client.get_state(self.ha_nissan_plugged_entity_id)
                        if plugged_state and 'state' in plugged_state:
                            plugged_in = plugged_state['state'] == 'on'

                    # Get range if available
                    range_km = 0
                    if self.ha_nissan_range_entity_id:
                        range_state = self.ha_client.get_state(self.ha_nissan_range_entity_id)
                        if range_state and 'state' in range_state:
                            try:
                                range_km = int(float(range_state['state']))
                            except ValueError:
                                pass

                    logger.info(f"NissanLeaf: HA data parsed: SoC={soc}%, Plugged={plugged_in}, Range={range_km}km")
                    return {
                        "vehicle": self.name,
                        "soc": int(soc),
                        "range_km": range_km,
                        "plugged_in": plugged_in
                    }
                except ValueError:
                    logger.error(f"NissanLeaf: HA SoC state is not a number: {state['state']}. Using fallback.")

        # Fallback to Mock/Manual
        logger.warning("NissanLeaf: HA integration not fully configured or failed. Using fallback mock data.")
        return {
            "vehicle": self.name,
            "soc": 0,
            "range_km": 0,
            "plugged_in": False
        }

    def get_soc(self):
        s = self.get_status()
        return s.get('soc', 0)