from abc import ABC, abstractmethod
import logging
import pycarwings2
import requests
import json # Import json for json.decoder.JSONDecodeError

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
            data = response.json()
            logger.info(f"HA: Received data for {entity_id}: {data}")
            return data
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
        self.username = config.get('username')
        self.password = config.get('password')
        self.region = config.get('region', 'NE')
        self.session = None
        self.leaf = None # Ensure leaf is initialized to None

    def _login(self):
        logger.info(f"NissanLeaf: Attempting login for user: {self.username}")
        if not self.username or not self.password:
            logger.error("NissanLeaf: Credentials missing from config.")
            return False
        try:
            self.session = pycarwings2.Session(self.username, self.password, self.region)
            # Try to get the leaf object
            if self.vin:
                # pycarwings2.Session.get_leaf(vin) may return a list or single object
                # Ensure it's handled correctly
                found_leaves = self.session.get_leaf(self.vin)
                if isinstance(found_leaves, list) and len(found_leaves) > 0:
                    self.leaf = found_leaves[0] # Take the first if multiple
                elif not isinstance(found_leaves, list):
                    self.leaf = found_leaves # Single object
                else:
                    logger.error(f"NissanLeaf: No leaf found for VIN {self.vin}.")
                    return False
            elif self.session.get_leaf(): # Get first available leaf if no VIN
                self.leaf = self.session.get_leaf()
            else:
                logger.error("NissanLeaf: No leaf objects returned from API.")
                return False

            logger.info("NissanLeaf: Login successful. Leaf object obtained.")
            return True
        except pycarwings2.CarwingsError as e: # Corrected exception type
            logger.error(f"NissanLeaf: pycarwings2 Login Failed: {e}. Check credentials or region.")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"NissanLeaf: Network/Request Error during login: {e}")
            return False
        except json.decoder.JSONDecodeError as e:
            logger.error(f"NissanLeaf: Server returned invalid JSON during login: {e}. Possible API change or bad response.")
            return False
        except Exception as e:
            logger.error(f"NissanLeaf: Unexpected Login Error: {e}")
            return False

    def get_status(self):
        logger.info("NissanLeaf: Attempting to get status.")
        if not self.session or not self.leaf: # Check both session AND leaf object
            if not self._login():
                logger.warning("NissanLeaf: Login failed, using fallback mock data.")
                return {"soc": 0, "range_km": 0, "plugged_in": False, "error": "Login failed"}
            
        try:
            # Check self.leaf again after successful _login()
            if not self.leaf:
                 logger.error("NissanLeaf: Leaf object not available after login attempt.")
                 return {"soc": 0, "range_km": 0, "plugged_in": False, "error": "Leaf object missing"}

            stats = self.leaf.get_latest_battery_status()
            logger.info(f"NissanLeaf: API data received: SOC={stats.battery_percent}")
            return {
                "vehicle": self.name,
                "soc": stats.battery_percent,
                "range_km": stats.cruising_range_ac_on_km,
                "plugged_in": stats.is_connected
            }
        except Exception as e:
            logger.error(f"NissanLeaf: Status Fetch Error: {e}. Using fallback mock data.")
            return {"soc": 0, "range_km": 0, "plugged_in": False, "error": str(e)}

    def get_soc(self):
        s = self.get_status()
        return s.get('soc', 0)
