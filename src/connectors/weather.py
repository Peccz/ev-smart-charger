import requests

class WeatherService:
    def __init__(self, lat, lon):
        self.lat = lat
        self.lon = lon
        self.base_url = "https://api.open-meteo.com/v1/forecast"

    def get_forecast(self, days=3):
        """
        Fetches weather forecast (temp, wind) for optimization.
        """
        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "hourly": "temperature_2m,wind_speed_10m",
            "forecast_days": days,
            "timezone": "Europe/Berlin" # Matches Sweden usually
        }
        
        try:
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            winds = hourly.get("wind_speed_10m", [])
            
            forecast = []
            for t, temp, wind in zip(times, temps, winds):
                forecast.append({
                    "time": t,
                    "temp_c": temp,
                    "wind_kmh": wind
                })
            return forecast
        except requests.RequestException as e:
            print(f"Error fetching weather: {e}")
            return []
