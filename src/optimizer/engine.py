import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import math

class Optimizer:
    def __init__(self, config):
        self.config = config
        self.buffer_threshold_price = config['optimization']['price_buffer_threshold']

    def suggest_action(self, vehicle, prices, weather_forecast):
        """
        Decides whether to charge NOW based on inputs.
        Returns: dict { "action": "CHARGE" | "IDLE", "reason": str }
        """
        status = vehicle.get_status()
        
        # 1. Basic checks
        if not status['plugged_in']:
            return {"action": "IDLE", "reason": "Vehicle not plugged in"}
        
        current_soc = status['soc']
        
        # Determine target SoC (Normal vs Buffer)
        base_target_soc = self.config['cars']['mercedes_eqv']['target_soc'] 
        if vehicle.name == "Nissan Leaf":
            base_target_soc = self.config['cars']['nissan_leaf']['target_soc']

        target_soc = base_target_soc
        is_buffering = False
        
        # Weather/Buffer Logic: If bad weather coming, increase target to 95%
        if self._should_buffer(prices, weather_forecast):
            target_soc = 95
            is_buffering = True

        if current_soc >= target_soc:
            return {"action": "IDLE", "reason": f"Target SoC {target_soc}% reached"}

        # 2. Calculate Energy Needs
        capacity_kwh = vehicle.capacity_kwh
        charge_speed_kw = vehicle.max_charge_kw
        
        soc_needed_percent = target_soc - current_soc
        kwh_needed = (soc_needed_percent / 100.0) * capacity_kwh
        hours_needed = math.ceil(kwh_needed / charge_speed_kw)
        
        if hours_needed <= 0:
             return {"action": "IDLE", "reason": "Calculation error: 0 hours needed"}

        # 3. Analyze Prices (Planning Horizon)
        if not prices:
            return {"action": "CHARGE", "reason": "No price data, failsafe charging"}

        # Filter prices: Look at prices starting NOW until tomorrow morning (e.g., 24h window)
        now = datetime.now()
        current_hour_str = now.strftime("%Y-%m-%dT%H:00:00") # Approximation for matching API format
        
        # Create DataFrame and sort by time
        df = pd.DataFrame(prices)
        
        # Ensure we only look at future/current prices
        # (Simple string comparison works for ISO format, but let's be robust if needed later)
        # Taking top X cheapest hours from the available list
        
        # If we have fewer hours of data than needed, charge now
        if len(df) < hours_needed:
             return {"action": "CHARGE", "reason": "Not enough price data to plan, charging now"}

        # Sort by Price (Lowest first)
        # We assume the list 'prices' covers the relevant planning period (e.g. next 24h)
        df_sorted = df.sort_values(by='price_sek', ascending=True)
        
        # Pick the cheapest N hours
        cheapest_hours = df_sorted.head(hours_needed)
        
        # Check if CURRENT hour is in the cheapest set
        # We compare the 'time_start' string. 
        # Note: The API format is usually "2023-10-27T14:00:00"
        # We need to match the current hour.
        
        current_hour_match = False
        # Simple check: Is the first item in the UNSORTED list (which is 'now') present in the CHEAPEST list?
        current_time_start = df.iloc[0]['time_start'] # The API returns sorted by time usually
        
        if current_time_start in cheapest_hours['time_start'].values:
            current_price = df.iloc[0]['price_sek']
            mode = "Buffering" if is_buffering else "Normal"
            return {
                "action": "CHARGE", 
                "reason": f"{mode}: Current hour ({current_price} SEK) is in top {hours_needed} cheapest hours needed to add {kwh_needed:.1f} kWh."
            }

        next_best_price = cheapest_hours['price_sek'].max()
        return {
            "action": "IDLE", 
            "reason": f"Waiting for cheaper hours (Need < {next_best_price} SEK). Current is {df.iloc[0]['price_sek']} SEK."
        }

    def _should_buffer(self, prices, weather):
        """
        Analyzes weather to predict price spikes.
        Low wind + Low Temp = High Price.
        """
        if not weather:
            return False
            
        df_weather = pd.DataFrame(weather)
        avg_wind = df_weather['wind_kmh'].mean()
        avg_temp = df_weather['temp_c'].mean()
        
        # Heuristic: If avg wind < 8 km/h and temp < -2C
        if avg_wind < 8 and avg_temp < -2:
            return True
            
        return False