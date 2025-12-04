import requests
from datetime import datetime, timedelta
import json

class SpotPriceService:
    def __init__(self, region="SE3"):
        self.region = region
        self.api_url = "https://www.elprisetjustnu.se/api/v1/prices"

    def get_prices(self, date=None):
        """
        Fetches spot prices for a specific date. 
        Defaults to today.
        Returns a list of dicts with 'time_start', 'price_sek'
        """
        if date is None:
            date = datetime.now()
        
        date_str = date.strftime("%Y/%m-%d")
        url = f"{self.api_url}/{date_str}_{self.region}.json"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            prices = []
            for entry in data:
                prices.append({
                    "time_start": entry["time_start"],
                    "price_sek": entry["SEK_per_kWh"],
                    "price_eur": entry["EUR_per_kWh"]
                })
            return prices
        except requests.RequestException as e:
            print(f"Error fetching prices: {e}")
            return []

    def get_prices_upcoming(self):
        """
        Fetches today's and tomorrow's prices (if available).
        """
        today = datetime.now()
        tomorrow = today + timedelta(days=1)
        
        prices = self.get_prices(today)
        prices_tomorrow = self.get_prices(tomorrow)
        
        if prices_tomorrow:
            prices.extend(prices_tomorrow)
            
        return prices
