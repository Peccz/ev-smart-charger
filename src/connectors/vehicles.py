from abc import ABC, abstractmethod
import logging
import pycarwings2
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
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching state for {entity_id} from HA: {e}")
            return None
            
# --- Vehicle Classes ---

class Vehicle(ABC):
    def __init__(self, name, capacity_kwh, max_charge_kw):
        self.name = name
        self.capacity_kwh = capacity_kwh
        self.max_charge_kw = max_charge_kw

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
        super().__init__("Mercedes EQV", config['capacity_kwh'], config['max_charge_rate_kw'])
        self.vin = config.get('vin')
        # Home Assistant Config
        self.ha_url = config.get('ha_url')
        self.ha_token = config.get('ha_token')
        self.ha_merc_soc_entity_id = config.get('ha_merc_soc_entity_id')
        
        self.ha_client = None
        if self.ha_url and self.ha_token:
            self.ha_client = HomeAssistantClient(self.ha_url, self.ha_token)

    def get_status(self):
        # 1. Try Home Assistant API
        if self.ha_client and self.ha_merc_soc_entity_id:
            state = self.ha_client.get_state(self.ha_merc_soc_entity_id)
            if state and 'state' in state:
                try:
                    soc = float(state['state'])
                    # HA doesn't always provide 'plugged_in' directly for all integrations
                    # We might need another sensor for that, or infer
                    plugged_in = True # Assume plugged in if SoC is available for now
                    if state.get('attributes', {}).get('charging', False) or state.get('attributes', {}).get('pluggedIn', False):
                        plugged_in = True
                    return {
                        "vehicle": self.name,
                        "soc": int(soc),
                        "range_km": int(state.get('attributes', {}).get('range', 0)), # Get range if available
                        "plugged_in": plugged_in
                    }
                except ValueError:
                    logger.warning(f"HA SoC state is not a number: {state['state']}")
        
        # 2. Fallback to Manual SoC from user_settings or mock
        # This will be picked up from web_app.py if HA fails
        logger.warning("Mercedes HA integration not configured or failed. Using fallback.")
        return {
            "vehicle": self.name,
            "soc": 45, # Fallback mock
            "range_km": 150,
            "plugged_in": True # Fallback mock
        }

    def get_soc(self):
        s = self.get_status()
        return s.get('soc', 0)

class NissanLeaf(Vehicle):
    def __init__(self, config):
        super().__init__("Nissan Leaf", config['capacity_kwh'], config['max_charge_kw'])
        self.vin = config.get('vin')
        self.username = config.get('username')
        self.password = config.get('password')
        self.region = config.get('region', 'NE')
        self.session = None

    def _login(self):
        if not self.username or not self.password:
            return
        try:
            self.session = pycarwings2.Session(self.username, self.password, self.region)
            if self.vin:
                self.leaf = self.session.get_leaf(self.vin)
            else:
                self.leaf = self.session.get_leaf()
        except Exception as e:
            logger.error(f"Nissan Login Failed: {e}")

    def get_status(self):
        if not self.session:
            self._login()
            
        if not self.session:
             return {"soc": 0, "range_km": 0, "plugged_in": False, "error": "No connection"}

        try:
            stats = self.leaf.get_latest_battery_status()
            return {
                "vehicle": self.name,
                "soc": stats.battery_percent,
                "range_km": stats.cruising_range_ac_on_km,
                "plugged_in": stats.is_connected
            }
        except Exception as e:
            logger.error(f"Nissan Status Error: {e}")
            return {"soc": 50, "range_km": 100, "plugged_in": False, "error": str(e)}

    def get_soc(self):
        s = self.get_status()
        return s.get('soc', 0)