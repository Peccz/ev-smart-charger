from abc import ABC, abstractmethod
import logging
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

    def call_service(self, domain, service, entity_id):
        url = f"{self.base_url}/api/services/{domain}/{service}"
        payload = {"entity_id": entity_id}
        logger.info(f"HA: Calling service {domain}.{service} for {entity_id}")
        try:
            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"HA: Error calling service {domain}.{service}: {e}")
            return False
            
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
    
    def start_climate(self):
        logger.warning(f"{self.name}: Climate control not implemented/configured.")
        return False

    def stop_climate(self):
        logger.warning(f"{self.name}: Climate control not implemented/configured.")
        return False

    def lock(self):
        logger.warning(f"{self.name}: Lock control not implemented/configured.")
        return False

    def unlock(self):
        logger.warning(f"{self.name}: Unlock control not implemented/configured.")
        return False

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
        self.ha_merc_plugged_entity_id = config.get('ha_merc_plugged_entity_id')
        self.ha_climate_id = config.get('climate_entity_id')
        self.ha_climate_status_id = config.get('climate_status_id')
        self.ha_lock_id = config.get('lock_entity_id')
        self.ha_odometer_id = config.get('odometer_entity_id')
        
        self.ha_client = None
        if self.ha_url and self.ha_token:
            self.ha_client = HomeAssistantClient(self.ha_url, self.ha_token)
            logger.info("MercedesEQV: HA client initialized.")
        else:
            logger.warning("MercedesEQV: HA credentials incomplete. Will use fallback.")

    def start_climate(self):
        if self.ha_client and self.ha_climate_id:
            # Detect if it's a button or switch
            domain = self.ha_climate_id.split('.')[0]
            service = "press" if domain == "button" else "turn_on"
            return self.ha_client.call_service(domain, service, self.ha_climate_id)
        return super().start_climate()

    def stop_climate(self):
        if self.ha_client and self.ha_climate_id:
            # Assuming separate stop entity OR toggle. 
            if "start" in self.ha_climate_id:
                stop_id = self.ha_climate_id.replace("start", "stop")
                return self.ha_client.call_service("button", "press", stop_id)
            
            domain = self.ha_climate_id.split('.')[0]
            if domain == "switch":
                return self.ha_client.call_service("switch", "turn_off", self.ha_climate_id)
        
        return super().stop_climate()

    def lock(self):
        if self.ha_client and self.ha_lock_id:
            return self.ha_client.call_service("lock", "lock", self.ha_lock_id)
        return super().lock()

    def unlock(self):
        if self.ha_client and self.ha_lock_id:
            return self.ha_client.call_service("lock", "unlock", self.ha_lock_id)
        return super().unlock()

    def get_status(self):
        logger.info("MercedesEQV: Attempting to get status from HA.")
        # 1. Try Home Assistant API
        if self.ha_client and self.ha_merc_soc_entity_id:
            state = self.ha_client.get_state(self.ha_merc_soc_entity_id)
            if state and 'state' in state:
                try:
                    soc = float(state['state'])
                    plugged_in = False # Default assumption
                    
                    # Check explicitly configured plugged/charging status sensor
                    if self.ha_merc_plugged_entity_id:
                        plug_status_entity = self.ha_client.get_state(self.ha_merc_plugged_entity_id)
                        if plug_status_entity and 'attributes' in plug_status_entity:
                            attrs = plug_status_entity['attributes']
                            # Option 1: Look for chargingactive attribute (binary)
                            if attrs.get('chargingactive', False):
                                plugged_in = True
                            # Option 2: Interpret chargingstatus attribute (state code)
                            elif 'chargingstatus' in attrs:
                                val = str(attrs['chargingstatus']).lower()
                                logger.info(f"MercedesEQV: Raw plugged status attribute value for {self.ha_merc_plugged_entity_id} (chargingstatus): '{val}'")
                                # Based on observed '3' when unplugged, let's assume 0 and 3 are unplugged
                                if val not in ['0', '3', 'disconnected', 'null', 'off', 'unavailable', 'unknown']:
                                    plugged_in = True
                            
                            logger.info(f"MercedesEQV: Plugged check ({self.ha_merc_plugged_entity_id} attributes) -> {plugged_in}")
                    
                    # Fallback: Original guess logic (if no dedicated plugged_entity_id provided)
                    elif state.get('attributes', {}).get('charging', False) or \
                         state.get('attributes', {}).get('pluggedIn', False) or \
                         state.get('attributes', {}).get('charge_port_door_closed', False) : 
                        plugged_in = True
                        
                    
                    odometer = 0
                    if self.ha_odometer_id:
                        odometer_state = self.ha_client.get_state(self.ha_odometer_id)
                        if odometer_state and 'state' in odometer_state:
                            try:
                                odometer = int(float(odometer_state['state']))
                            except ValueError:
                                pass

                    range_km = 0
                    range_state = self.ha_client.get_state("sensor.urg48t_range_electric") # Get range from dedicated sensor
                    if range_state and 'state' in range_state:
                        try:
                            range_km = int(float(range_state['state']))
                        except ValueError:
                            pass
                    
                    climate_active = False
                    if self.ha_climate_status_id:
                        c_state = self.ha_client.get_state(self.ha_climate_status_id)
                        if c_state and 'state' in c_state:
                            val = str(c_state['state']).lower()
                            logger.info(f"MercedesEQV: Climate status ({self.ha_climate_status_id}) = {val}")
                            if val in ['on', 'true', '1', 'active']:
                                climate_active = True

                    logger.info(f"MercedesEQV: HA data parsed: SoC={soc}%, Plugged={plugged_in}, Odometer={odometer}, Range={range_km}km")
                    return {
                        "vehicle": self.name,
                        "soc": int(soc),
                        "range_km": range_km, 
                        "plugged_in": plugged_in,
                        "odometer": odometer,
                        "climate_active": climate_active
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
        self.ha_climate_id = config.get('climate_entity_id')
        self.ha_odometer_id = config.get('odometer_entity_id')

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

    def start_climate(self):
        if self.ha_client and self.ha_climate_id:
            return self.ha_client.call_service("switch", "turn_on", self.ha_climate_id)
        return super().start_climate()
    
    def stop_climate(self):
        if self.ha_client and self.ha_climate_id:
            return self.ha_client.call_service("switch", "turn_off", self.ha_climate_id)
        return super().stop_climate()

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
                    
                    odometer = 0
                    if self.ha_odometer_id:
                        odometer_state = self.ha_client.get_state(self.ha_odometer_id)
                        if odometer_state and 'state' in odometer_state:
                            try:
                                odometer = int(float(odometer_state['state']))
                            except ValueError:
                                pass
                    
                    climate_active = False
                    if self.ha_climate_id:
                        c_state = self.ha_client.get_state(self.ha_climate_id)
                        if c_state and 'state' in c_state:
                            if str(c_state['state']).lower() in ['on', 'true', '1', 'active']:
                                climate_active = True

                    logger.info(f"NissanLeaf: HA data parsed: SoC={soc}%, Plugged={plugged_in}, Range={range_km}km, Odometer={odometer}")
                    return {
                        "vehicle": self.name,
                        "soc": int(soc),
                        "range_km": range_km,
                        "plugged_in": plugged_in,
                        "odometer": odometer,
                        "climate_active": climate_active
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