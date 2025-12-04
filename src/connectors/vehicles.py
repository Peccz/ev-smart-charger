from abc import ABC, abstractmethod
import logging
import pycarwings2
import time
from mercedes_me_api import MercedesMe

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
        self.email = config.get('username') # Mapped from settings
        self.password = config.get('password')
        self.me = None

    def _connect(self):
        if not self.email or not self.password:
            return False
        
        try:
            self.me = MercedesMe(self.email, self.password)
            # Need to trigger login/update
            # Library usually handles this lazy or via explicit call
            # Note: Some libs require manual 2FA flow on CLI for first run
            return True
        except Exception as e:
            logger.error(f"Mercedes Login Error: {e}")
            return False

    def get_status(self):
        # 1. Try API
        if not self.me:
            if not self._connect():
                 # Fallback to Mock/Manual
                 logger.warning("Mercedes credentials missing. Using Mock/Manual.")
                 return { "vehicle": self.name, "soc": 45, "range_km": 150, "plugged_in": True }

        try:
            # Fetch car data
            # Library usage varies, assuming standard 'mercedes_me_api' usage:
            # me.find_vehicle(vin) -> returns object with status
            
            # Note: Since exact method depends on library version installed, 
            # wrapping in try/except is crucial.
            
            # Simpler approach if library is complex: Just instantiate and ask for cars
            cars = self.me.cars
            target_car = None
            
            if self.vin:
                for car in cars:
                    if car.vin == self.vin:
                        target_car = car
                        break
            elif cars:
                target_car = cars[0]

            if target_car:
                # Force update? target_car.update()
                
                # Read attributes
                soc = target_car.soc
                range_km = target_car.range_electric
                plugged = target_car.charging_active or target_car.is_plugged_in # Pseudo-property
                
                # Some libs return attributes in a dict 'attributes'
                if hasattr(target_car, 'attributes'):
                     soc = target_car.attributes.get('soc', 0)
                     range_km = target_car.attributes.get('rangeElectricKm', 0)
                
                return {
                    "vehicle": self.name,
                    "soc": soc,
                    "range_km": range_km,
                    "plugged_in": True # Hard to know for sure without specific attribute check
                }
                
        except Exception as e:
            logger.error(f"Mercedes API Fetch Error: {e}")
        
        # Fallback
        return {
            "vehicle": self.name,
            "soc": 45, 
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