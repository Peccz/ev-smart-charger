from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)

class BaseConnector(ABC):
    def __init__(self, config):
        self.config = config
        self.validate_config()

    @abstractmethod
    def validate_config(self):
        """Check if required config keys are present."""
        pass

class Vehicle(BaseConnector):
    @abstractmethod
    def get_status(self):
        """
        Returns a dict with standardized keys:
        - soc (int): State of Charge %
        - range_km (int): Estimated range
        - plugged_in (bool): True if cable connected
        - odometer (int): Total distance driven
        - climate_active (bool): True if pre-conditioning
        """
        pass

class Charger(BaseConnector):
    @abstractmethod
    def get_status(self):
        """
        Returns a dict with standardized keys:
        - is_charging (bool)
        - power_kw (float)
        - operating_mode (str): e.g. 'CHARGING', 'DISCONNECTED'
        """
        pass

    @abstractmethod
    def start_charging(self):
        pass

    @abstractmethod
    def stop_charging(self):
        pass
