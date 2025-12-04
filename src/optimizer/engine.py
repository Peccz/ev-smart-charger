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
                    valid = {}
                    now = datetime.now()
                    for vid, override in data.items():
                        expires = dateutil.parser.parse(override['expires_at'])
                        if expires.tzinfo is None:
                            expires = expires.replace(tzinfo=None) 
                        if expires > now:
                            valid[vid] = override
                    return valid
            except Exception as e:
                print(f"Error reading overrides: {e}")
        return {}

    def calculate_urgency(self, vehicle, target_soc):
        """
        Calculates how urgent the charging need is.
        Score = kWh needed / Max Charge Speed.
        Example: Need 40kWh, Speed 11kW => Score 3.6 (Hours needed).
        Higher score = Higher priority.
        """
        status = vehicle.get_status()
        soc = status['soc']
        
        if soc >= target_soc:
            return 0.0
            
        capacity = vehicle.capacity_kwh
        needed_soc = target_soc - soc
        needed_kwh = (needed_soc / 100.0) * capacity
        
        # Hours needed at full speed
        hours_needed = needed_kwh / vehicle.max_charge_kw
        return hours_needed

    def suggest_action(self, vehicle, prices, weather_forecast):
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
        current_soc = status['soc']
        
        # Determine target SoC
        user_settings = self._get_user_settings()
        target_soc = user_settings.get(f"{vehicle_id}_target", 80)
        
        is_buffering = False
        if self._should_buffer(prices, weather_forecast):
            target_soc = 95
            is_buffering = True

        if current_soc >= target_soc:
            return {"action": "IDLE", "reason": f"Target SoC {target_soc}% reached"}

        # 1. Calculate Energy Needs
        capacity_kwh = vehicle.capacity_kwh
        charge_speed_kw = vehicle.max_charge_kw
        
        soc_needed_percent = target_soc - current_soc
        kwh_needed = (soc_needed_percent / 100.0) * capacity_kwh
        hours_needed = math.ceil(kwh_needed / charge_speed_kw)
        
        # 2. Basic checks
        if not status['plugged_in']:
            # Even if not plugged in, we return what we WOULD do
            # The main loop handles the "Plug me in" logic based on this + urgency
            return {"action": "IDLE", "reason": "Vehicle not plugged in (Waiting for connection)"}

        if hours_needed <= 0:
             return {"action": "IDLE", "reason": "Calculation error: 0 hours needed"}

        # 3. Analyze Prices
        if not prices:
            return {"action": "CHARGE", "reason": "No price data, failsafe charging"}

        now = datetime.now()
        df = pd.DataFrame(prices)
        
        if len(df) < hours_needed:
             return {"action": "CHARGE", "reason": "Not enough price data, charging now"}

        df_sorted = df.sort_values(by='price_sek', ascending=True)
        cheapest_hours = df_sorted.head(hours_needed)
        
        current_time_start = df.iloc[0]['time_start']
        
        if current_time_start in cheapest_hours['time_start'].values:
            current_price = df.iloc[0]['price_sek']
            mode = "Buffering" if is_buffering else "Normal"
            return {
                "action": "CHARGE", 
                "reason": f"{mode}: Current hour ({current_price} SEK) is cheap."
            }

        next_best_price = cheapest_hours['price_sek'].max()
        return {
            "action": "IDLE", 
            "reason": f"Waiting for cheaper hours (Need < {next_best_price} SEK)."
        }

    def _should_buffer(self, prices, weather):
        if not weather:
            return False
        df_weather = pd.DataFrame(weather)
        avg_wind = df_weather['wind_kmh'].mean()
        avg_temp = df_weather['temp_c'].mean()
        if avg_wind < 8 and avg_temp < -2:
            return True
        return False