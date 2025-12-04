from abc import ABC, abstractmethod
import logging
import pycarwings2
import time

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
        self.username = config.get('username')
        self.password = config.get('password')
        
        # Mercedes API is complex (OAuth2). 
        # Ideally, use a dedicated library or integration (like Home Assistant) 
        # and read status from there via webhook/API.
        # For now, we keep the simulation fallback if auth fails/missing.

    def get_soc(self):
        # TODO: Implement robust Mercedes Me OAuth flow
        # Currently returning simulation data to prevent crash
        logger.warning("Mercedes API not fully implemented (requires OAuth). Using mock data.")
        return 45

    def get_status(self):
        # Simulation fallback
        return {
            "vehicle": self.name,
            "soc": self.get_soc(),
            "range_km": 150,
            "plugged_in": True # Assume plugged in for testing
        }

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
            logger.error("Nissan credentials missing")
            return
            
        logger.info("Logging in to Nissan Connect...")
        try:
            self.session = pycarwings2.Session(self.username, self.password, self.region)
            # If VIN provided, select specific car, else first one
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
            # Request update from car (warning: takes time and battery)
            # Ideally, get cached status first
            # status = self.leaf.get_latest_battery_status() 
            
            # For now, let's fetch latest known from server (fast)
            # To force update from car: self.leaf.request_update() (blocking, slow)
            
            stats = self.leaf.get_latest_battery_status()
            
            return {
                "vehicle": self.name,
                "soc": stats.battery_percent,
                "range_km": stats.cruising_range_ac_on_km, # Estimate
                "plugged_in": stats.is_connected # Assuming this field exists in response
            }
        except Exception as e:
            logger.error(f"Nissan Status Error: {e}")
            # Return fallback or last known
            return {"soc": 50, "range_km": 100, "plugged_in": False, "error": str(e)}

    def get_soc(self):
        s = self.get_status()
        return s.get('soc', 0)