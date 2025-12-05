import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import math
import json
import os
import dateutil.parser
import logging

logger = logging.getLogger(__name__)

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
            except Exception as e:
                logger.error(f"Error loading user settings: {e}")
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
                logger.error(f"Error reading overrides: {e}")
        return {}

    def _generate_price_forecast(self, current_prices, weather_forecast, forecast_horizon_days=3):
        """
        Extends official price data with a forecast based on historical patterns and weather.
        Simple model: Assume average price, adjust based on wind speed (low wind = higher price).
        """
        now = datetime.now()
        forecast_end_time = now + timedelta(days=forecast_horizon_days)
        
        # Convert official prices to DataFrame
        official_prices_df = pd.DataFrame(current_prices)
        if not official_prices_df.empty:
            official_prices_df['time_start'] = pd.to_datetime(official_prices_df['time_start'], utc=True).dt.tz_convert('Europe/Berlin').dt.tz_localize(None)
            official_prices_df = official_prices_df.set_index('time_start')
            # Resample to hourly if we have 15-min data, taking the mean price for the hour
            # This ensures we have a value for the :00 timestamp that represents the hour
            official_prices_df = official_prices_df.resample('1h').mean()
        
        all_forecast_prices = []

        for hour_data in weather_forecast:
            hour_time = pd.to_datetime(hour_data['time']) # These are naive local times from OpenMeteo (Europe/Berlin requested)
            
            if hour_time < now.replace(minute=0, second=0, microsecond=0): # Skip past hours (align to hour start)
                continue
            
            # If we have an official price, use it
            if hour_time in official_prices_df.index:
                all_forecast_prices.append({
                    "time_start": hour_time,
                    "price_sek": official_prices_df.loc[hour_time]['price_sek'],
                    "source": "Official"
                })
                continue

            # If no official price, generate a forecast
            if hour_time > forecast_end_time: # Only forecast up to desired horizon
                continue
            
            # Simple heuristic: average price + wind factor
            base_price_sek = official_prices_df['price_sek'].mean() if not official_prices_df.empty else 0.5 # Fallback to 0.5 SEK
            
            # Wind speed (use 80m for better correlation with wind power generation)
            wind_speed = hour_data.get('wind_kmh_80m', 10) # Default to 10 if not available

            # Wind factor: Lower wind = higher price, up to a certain threshold
            wind_price_factor = 1.0
            if wind_speed < 10: # Low wind (e.g., < 10 km/h)
                wind_price_factor = 1.0 + (10 - wind_speed) * 0.05 # +5% for every 1 km/h below 10
            elif wind_speed > 30: # Very high wind (e.g., > 30 km/h)
                wind_price_factor = 1.0 - (wind_speed - 30) * 0.01 # -1% for every 1 km/h above 30

            forecasted_price_sek = base_price_sek * wind_price_factor
            
            # Ensure price is not negative or excessively high
            forecasted_price_sek = max(0.01, min(forecasted_price_sek, 5.0)) # 0.01 to 5 SEK
            
            all_forecast_prices.append({
                "time_start": hour_time,
                "price_sek": forecasted_price_sek,
                "source": "Forecasted"
            })
        
        # Sort and remove duplicates (if official prices overlapped)
        full_price_df = pd.DataFrame(all_forecast_prices)
        if not full_price_df.empty:
            full_price_df = full_price_df.drop_duplicates(subset=['time_start'], keep='first')
            full_price_df = full_price_df.sort_values(by='time_start')
            full_price_df['time_start'] = full_price_df['time_start'].apply(lambda x: x.isoformat()) # Corrected line
            return full_price_df.to_dict(orient='records')
        return []

    def calculate_urgency(self, vehicle, target_soc):
        """
        Calculates how urgent the charging need is (in hours).
        Higher score = Higher priority.
        """
        status = vehicle.get_status()
        soc = status['soc']
        
        # Define needed_kwh here to ensure it's always defined
        needed_kwh = 0.0 
        
        if soc < target_soc: # Only calculate if charging is actually needed
            capacity = vehicle.capacity_kwh
            needed_soc_percent = target_soc - soc # Renamed to avoid confusion
            needed_kwh = (needed_soc_percent / 100.0) * capacity # Define needed_kwh here
        
        # Hours needed at full speed (will be 0 if needed_kwh is 0)
        hours_needed = needed_kwh / vehicle.max_charge_kw if vehicle.max_charge_kw > 0 else 0.0
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
        if self._should_buffer(prices, weather_forecast): # Still use the simple buffer logic
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
            return {"action": "IDLE", "reason": "Vehicle not plugged in (Waiting for connection)"}

        if hours_needed <= 0:
             return {"action": "IDLE", "reason": "Calculation error: 0 hours needed"}

        # 3. Analyze Prices (Planning Horizon)
        if not prices:
            logger.warning("Optimizer: No price data. Failsafe charging enabled.")
            return {"action": "CHARGE", "reason": "No price data, failsafe charging"}

        now = datetime.now()
        df = pd.DataFrame(prices)
        
        # The prices passed here are already the full (official + forecasted) list
        
        if len(df) < hours_needed:
             logger.warning(f"Optimizer: Not enough price data ({len(df)}h) to plan {hours_needed}h. Failsafe charging enabled.")
             return {"action": "CHARGE", "reason": "Not enough price data, failsafe charging"}

        df_sorted = df.sort_values(by='price_sek', ascending=True)
        cheapest_hours = df_sorted.head(hours_needed)['time_start'].tolist()
        
        current_time_start = df.iloc[0]['time_start']
        
        if current_time_start in cheapest_hours: # Check using the full ISO string
            current_price = df.iloc[0]['price_sek']
            mode = "Buffering" if is_buffering else "Normal"
            return {
                "action": "CHARGE", 
                "reason": f"{mode}: Current hour ({current_price:.2f} SEK) is cheap."
            }

        next_best_price = df_sorted.head(hours_needed)['price_sek'].max() # Price of the most expensive hour in the cheapest block
        return {
            "action": "IDLE", 
            "reason": f"Waiting for cheaper hours (Need < {next_best_price:.2f} SEK). Current is {df.iloc[0]['price_sek']:.2f} SEK."
        }

    def _should_buffer(self, prices, weather):
        """
        Analyzes weather to predict price spikes.
        Low wind + Low Temp = High Price.
        """
        if not weather:
            return False
            
        df_weather = pd.DataFrame(weather)
        avg_wind_80m = df_weather['wind_kmh_80m'].mean() # Use higher altitude wind for generation forecast
        avg_temp = df_weather['temp_c'].mean()
        
        # Heuristic: If avg wind < 8 km/h and temp < -2C, prices usually spike in SE3
        if avg_wind_80m < 8 and avg_temp < -2:
            logger.info("Optimizer: Buffering suggested due to predicted low wind and low temperature.")
            return True
            
        return False
