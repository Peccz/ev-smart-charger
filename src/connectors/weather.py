import requests
import logging
import time

logger = logging.getLogger(__name__)

class WeatherService:
    def __init__(self, lat, lon):
        self.lat = lat
        self.lon = lon
        self.base_url = "https://api.open-meteo.com/v1/forecast"
        self._cache = None
        self._cache_time = 0
        self._cache_ttl = 900 # 15 minutes cache

    def get_forecast(self, days=5): # Increased to 5 days for longer term planning
        """
        Fetches weather forecast (temp, wind, solar) for optimization.
        Uses in-memory caching to avoid rate limits.
        """
        if self._cache and (time.time() - self._cache_time < self._cache_ttl):
            return self._cache

        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "hourly": "temperature_2m,wind_speed_10m,wind_speed_80m,wind_speed_120m,shortwave_radiation", # Added solar radiation
            "forecast_days": days,
            "timezone": "Europe/Berlin"
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            winds_10m = hourly.get("wind_speed_10m", [])
            winds_80m = hourly.get("wind_speed_80m", [])
            winds_120m = hourly.get("wind_speed_120m", [])
            rads = hourly.get("shortwave_radiation", []) # Solar radiation
            
            forecast = []
            for i in range(len(times)):
                forecast.append({
                    "time": times[i],
                    "temp_c": temps[i],
                    "wind_kmh_10m": winds_10m[i],
                    "wind_kmh_80m": winds_80m[i],
                    "wind_kmh_120m": winds_120m[i],
                    "solar_w_m2": rads[i] if i < len(rads) else 0
                })
            
            self._cache = forecast
            self._cache_time = time.time()
            logger.info(f"WeatherService: Fetched {len(forecast)} hours of forecast data (fresh).")
            return forecast
        except requests.RequestException as e:
            logger.error(f"WeatherService: Error fetching forecast: {e}")
            # Return cached data if available even if expired, as fallback
            if self._cache:
                logger.warning("WeatherService: Using expired cache due to API error.")
                return self._cache
            return []
