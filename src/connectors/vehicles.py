from abc import ABC, abstractmethod
import logging
import requests
import json # Import json for json.decoder.JSONDecodeError

# Import the new Kamereon client
from kamereon_python import KamereonClient, NissanConnectVehicle # Adjust import based on library structure

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
        self.username = config.get('username')
        self.password = config.get('password')
        self.region = config.get('region', 'NE') # Default to Europe
        self.kamereon_client = None
        self.nissan_vehicle = None
        self.kamereon_enabled = False

        if self.username and self.password:
            self.kamereon_enabled = True
            logger.info("NissanLeaf: Kamereon client enabled with credentials.")
        else:
            logger.warning("NissanLeaf: Kamereon credentials missing. Will rely on manual input.")

    def _connect(self):
        if not self.kamereon_enabled:
            return False

        logger.info(f"NissanLeaf: Attempting connection for user: {self.username}")
        if not self.username or not self.password:
            logger.error("NissanLeaf: Credentials missing from config.")
            self.kamereon_enabled = False # Disable further attempts
            return False
        
        try:
            # KamereonClient expects email, password, and optional region code
            self.kamereon_client = KamereonClient(self.username, self.password, self.region)
            self.kamereon_client.connect() # Establish connection and get token
            logger.info("NissanLeaf: KamereonClient connected.")

            # Get the vehicle object
            vehicles = self.kamereon_client.get_vehicles()
            if not vehicles:
                logger.error("NissanLeaf: No vehicles found for this account.")
                self.kamereon_enabled = False
                return False
            
            if self.vin:
                # Filter by VIN if provided
                for v in vehicles:
                    if v.vin == self.vin:
                        self.nissan_vehicle = v
                        break
                if not self.nissan_vehicle:
                    logger.error(f"NissanLeaf: Vehicle with VIN {self.vin} not found.")
                    self.kamereon_enabled = False
                    return False
            else:
                # Take the first vehicle if VIN not specified
                self.nissan_vehicle = vehicles[0]
                logger.info(f"NissanLeaf: Using first vehicle found: {self.nissan_vehicle.vin}")
            
            logger.info("NissanLeaf: Vehicle object obtained.")
            return True

        except Exception as e:
            logger.error(f"NissanLeaf: Kamereon connection failed: {e}. Check credentials, VIN, or API changes.")
            self.kamereon_enabled = False # Disable on failure
            return False

    def get_status(self):
        logger.info("NissanLeaf: Attempting to get status.")
        if not self.kamereon_enabled:
            logger.warning("NissanLeaf: Kamereon is disabled. Using fallback mock data.")
            return {"vehicle": self.name, "soc": 0, "range_km": 0, "plugged_in": False, "error": "Kamereon disabled"}

        if not self.kamereon_client or not self.nissan_vehicle:
            if not self._connect():
                logger.warning("NissanLeaf: Connection failed. Using fallback mock data.")
                return {"soc": 0, "range_km": 0, "plugged_in": False, "error": "Connection failed"}
            
        try:
            # Fetch fresh data from the vehicle
            self.nissan_vehicle.update_status() # This method updates internal state
            
            soc = self.nissan_vehicle.battery_level
            # Kamereon API can provide charging status
            plugged_in = self.nissan_vehicle.is_charging or self.nissan_vehicle.is_plugged_in # Check relevant attributes
            range_km = self.nissan_vehicle.range_electric

            logger.info(f"NissanLeaf: API data received: SOC={soc}, Plugged={plugged_in}, Range={range_km}")
            return {
                "vehicle": self.name,
                "soc": int(soc),
                "range_km": int(range_km),
                "plugged_in": plugged_in
            }
        except Exception as e:
            logger.error(f"NissanLeaf: Status Fetch Error: {e}. Using fallback mock data.")
            return {"soc": 0, "range_km": 0, "plugged_in": False, "error": str(e)}

    def get_soc(self):
        s = self.get_status()
        return s.get('soc', 0)
