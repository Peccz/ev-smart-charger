from abc import ABC, abstractmethod
import logging
import pycarwings2
import time
from connectors.mercedes_auth import MercedesClient

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
        # Try to init client from saved token or config
        # We instantiate a fresh client here to check for token file
        self.client = MercedesClient(
            config.get('client_id', ''), 
            config.get('client_secret', '')
        )

    def get_status(self):
        # 1. Try Real API
        if self.client.token:
            data = self.client.get_status(self.vin)
            if data:
                return {
                    "vehicle": self.name,
                    "soc": data['soc'],
                    "range_km": data['range_km'],
                    "plugged_in": data['plugged_in']
                }
        
        # 2. Fallback / Mock
        logger.warning("Mercedes API Token missing. Using Mock Data (45%).")
        return {
            "vehicle": self.name,
            "soc": 45, # Mock
            "range_km": 150,
            "plugged_in": True # Mock
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
            # Return fallback
            return {"soc": 50, "range_km": 100, "plugged_in": False, "error": str(e)}

    def get_soc(self):
        s = self.get_status()
        return s.get('soc', 0)
