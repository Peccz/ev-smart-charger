from abc import ABC, abstractmethod
import logging
from datetime import datetime, timedelta

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
    def __init__(self, config):
        super().__init__(config)
        self._last_status = None
        self._last_status_time = None
        self._cache_ttl_minutes = 30

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

    def _get_cached_status(self, current_status):
        """Helper to cache successful status and return cache on failure."""
        now = datetime.now()
        
        # If current fetch was successful (e.g. SoC > 0 or similar indicator)
        # We assume success if we got a dict with some real data
        is_success = current_status and current_status.get('soc', 0) > 0
        
        if is_success:
            self._last_status = current_status
            self._last_status_time = now
            return current_status
        
        # If fetch failed, check cache
        if self._last_status and self._last_status_time:
            age = now - self._last_status_time
            if age < timedelta(minutes=self._cache_ttl_minutes):
                logger.warning(f"{self.__class__.__name__}: API failure, using cached status from {age.total_seconds()/60:.1f}m ago")
                return self._last_status
        
        return current_status

    def wake_up(self):
        """
        Force vehicle to wake up and update status.
        Returns True if command sent successfully.
        """
        return False

    def start_charging(self):
        """Optional: Send start charge command to vehicle."""
        return False

    def stop_charging(self):
        """Optional: Send stop charge command to vehicle."""
        return False

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
