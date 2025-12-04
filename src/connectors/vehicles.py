from abc import ABC, abstractmethod
import logging
import pycarwings2
import requests
from connectors.mercedes_api.token_client import MercedesTokenClient

logger = logging.getLogger(__name__)

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
        self.token_client = MercedesTokenClient()

    def get_status(self):
        token = self.token_client.get_valid_token()
        
        if token and self.vin:
            try:
                # Fetch status from BFF (Backend for Frontend) API
                # This endpoint mimics the app call
                url = "https://bff.mercedes-benz.com/vehicle/v1/vehicles"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "X-SessionId": "00000000-0000-0000-0000-000000000000", # Or random
                    "Accept-Language": "en-US"
                }
                
                # 1. Get list of vehicles to find ours (and get basic status)
                r = requests.get(url, headers=headers)
                r.raise_for_status()
                data = r.json()
                
                target_car = None
                for car in data:
                    if car.get('finorvin') == self.vin:
                        target_car = car
                        break
                
                if target_car:
                    soc = target_car.get('soc', 0)
                    # Check specific EV status if needed, but summary usually has soc
                    return {
                        "vehicle": self.name,
                        "soc": soc,
                        "range_km": 0, # Might need deeper call
                        "plugged_in": True # Simplify or check 'chargingActive'
                    }
                    
            except Exception as e:
                logger.error(f"Mercedes API Error: {e}")

        # Fallback
        return {
            "vehicle": self.name,
            "soc": 45, # Fallback
            "range_km": 150,
            "plugged_in": True
        }

    def get_soc(self):
        s = self.get_status()
        return s.get('soc', 0)

class NissanLeaf(Vehicle):
    def __init__(self, config):
        super().__init__("Nissan Leaf", config['capacity_kwh'], config['max_charge_rate_kw'])
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
