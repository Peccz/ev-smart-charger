from abc import ABC, abstractmethod
import random # For simulation

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
        self.vin = config['vin']
        # Placeholder for API client authentication

    def get_soc(self):
        # TODO: Replace with actual API call to Mercedes Me
        # return self.api.get_soc(self.vin)
        return 45 # Simulation

    def get_status(self):
        # Simulation
        return {
            "vehicle": self.name,
            "soc": self.get_soc(),
            "range_km": 150,
            "plugged_in": True
        }

class NissanLeaf(Vehicle):
    def __init__(self, config):
        super().__init__("Nissan Leaf", config['capacity_kwh'], config['max_charge_rate_kw'])
        self.vin = config['vin']
        # Placeholder for API client authentication

    def get_soc(self):
        # TODO: Replace with actual API call to Nissan Connect
        return 60 # Simulation

    def get_status(self):
        # Simulation
        return {
            "vehicle": self.name,
            "soc": self.get_soc(),
            "range_km": 120,
            "plugged_in": False
        }
