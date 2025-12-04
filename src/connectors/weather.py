import requests
import logging

logger = logging.getLogger(__name__)

class WeatherService:
    def __init__(self, lat, lon):
        self.lat = lat
        self.lon = lon
        self.base_url = "https://api.open-meteo.com/v1/forecast"

    def get_forecast(self, days=5): # Increased to 5 days for longer term planning
        """
        Fetches weather forecast (temp, wind) for optimization.
        """
        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "hourly": "temperature_2m,wind_speed_10m,wind_speed_80m,wind_speed_120m", # More detailed wind
            "forecast_days": days,
            "timezone": "Europe/Berlin"
        }
        
        try:
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            winds_10m = hourly.get("wind_speed_10m", [])
            winds_80m = hourly.get("wind_speed_80m", [])
            winds_120m = hourly.get("wind_speed_120m", [])
            
            forecast = []
            for i in range(len(times)):
                forecast.append({
                    "time": times[i],
                    "temp_c": temps[i],
                    "wind_kmh_10m": winds_10m[i],
                    "wind_kmh_80m": winds_80m[i],
                    "wind_kmh_120m": winds_120m[i]
                })
            logger.info(f"WeatherService: Fetched {len(forecast)} hours of forecast data.")
            return forecast
        except requests.RequestException as e:
            logger.error(f"WeatherService: Error fetching forecast: {e}")
            return []