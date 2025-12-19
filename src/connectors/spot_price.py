import requests
from datetime import datetime, timedelta
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

CACHE_FILE = "data/price_history_cache.json"

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
            response = requests.get(url, timeout=10)
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
            logger.error(f"SpotPriceService: Error fetching prices for {date_str}: {e}")
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

    def get_historical_average(self, days=30):
        """
        Calculates the average price over the last X days.
        Uses local cache to avoid spamming the API.
        """
        cache = {}
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    cache = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load price cache: {e}")

        total_sum = 0
        total_count = 0
        cache_updated = False
        
        today = datetime.now()
        
        # Cleanup old cache entries (older than 40 days to keep it clean)
        limit_date = (today - timedelta(days=40)).strftime("%Y-%m-%d")
        keys_to_del = [k for k in cache.keys() if k < limit_date]
        for k in keys_to_del:
            del cache[k]
            cache_updated = True

        for i in range(1, days + 1):
            day = today - timedelta(days=i)
            day_key = day.strftime("%Y-%m-%d")
            
            day_prices = cache.get(day_key)
            
            if day_prices is None:
                logger.info(f"Fetching historical prices for {day_key}...")
                fetched = self.get_prices(day)
                if fetched:
                    # Extract just the float values to save space
                    day_prices = [p['price_sek'] for p in fetched]
                    cache[day_key] = day_prices
                    cache_updated = True
                    time.sleep(0.1) # Be nice to API
                else:
                    logger.warning(f"Could not fetch history for {day_key}")
                    continue
            
            if day_prices:
                total_sum += sum(day_prices)
                total_count += len(day_prices)

        if cache_updated:
            try:
                os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
                with open(CACHE_FILE, 'w') as f:
                    json.dump(cache, f)
            except Exception as e:
                logger.error(f"Failed to save price cache: {e}")

        if total_count == 0:
            return 0.5 # Fallback default

        return total_sum / total_count
