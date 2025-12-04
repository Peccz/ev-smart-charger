import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import math
import json
import os
import dateutil.parser

class Optimizer:
    def __init__(self, config):
        self.config = config
        self.buffer_threshold_price = config['optimization']['price_buffer_threshold']
        self.settings_path = "data/user_settings.json"
        self.overrides_path = "data/manual_overrides.json"

    def _get_user_settings(self):
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _get_overrides(self):
        if os.path.exists(self.overrides_path):
            try:
                with open(self.overrides_path, 'r') as f:
                    data = json.load(f)
                    # Filter out expired
                    valid = {}
                    now = datetime.now()
                    for vid, override in data.items():
                        expires = dateutil.parser.parse(override['expires_at'])
                        # Naive comparison fix (assuming local time everywhere for simplicity in this context)
                        if expires.tzinfo is None:
                            expires = expires.replace(tzinfo=None) 
                        
                        if expires > now:
                            valid[vid] = override
                    return valid
            except Exception as e:
                print(f"Error reading overrides: {e}")
        return {}

    def suggest_action(self, vehicle, prices, weather_forecast):
        """
        Decides whether to charge NOW based on inputs.
        Returns: dict { "action": "CHARGE" | "IDLE", "reason": str }
        """
        # 0. Check Manual Overrides
        overrides = self._get_overrides()
        vehicle_id = "mercedes_eqv" if "Mercedes" in vehicle.name else "nissan_leaf"
        
        if vehicle_id in overrides:
            ovr = overrides[vehicle_id]
            if ovr['action'] == "CHARGE":
                return {"action": "CHARGE", "reason": "Manual Override (Ladda Nu!)"}
            if ovr['action'] == "STOP":
                return {"action": "IDLE", "reason": "Manual Override (Stoppa)"}

        status = vehicle.get_status()
        
        # 1. Basic checks
        if not status['plugged_in']:
            return {"action": "IDLE", "reason": "Vehicle not plugged in"}
        
        current_soc = status['soc']
        
        # Determine target SoC from User Settings
        user_settings = self._get_user_settings()
        target_soc = user_settings.get(f"{vehicle_id}_target", 80) # Default 80 if not set
        
        is_buffering = False
        
        # Weather/Buffer Logic
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
        
        # Create DataFrame and sort by time
        df = pd.DataFrame(prices)
        
        # Ensure we only look at future/current prices
        # Taking top X cheapest hours from the available list
        
        if len(df) < hours_needed:
             return {"action": "CHARGE", "reason": "Not enough price data to plan, charging now"}

        # Sort by Price (Lowest first)
        df_sorted = df.sort_values(by='price_sek', ascending=True)
        
        # Pick the cheapest N hours
        cheapest_hours = df_sorted.head(hours_needed)
        
        # Check if CURRENT hour is in the cheapest set
        current_time_start = df.iloc[0]['time_start'] # The API returns sorted by time usually
        
        if current_time_start in cheapest_hours['time_start'].values:
            current_price = df.iloc[0]['price_sek']
            mode = "Buffering" if is_buffering else "Normal"
            return {
                "action": "CHARGE", 
                "reason": f"{mode}: Current hour ({current_price} SEK) is in top {hours_needed} cheapest hours needed to add {kwh_needed:.1f} kWh (Target: {target_soc}%)."
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
