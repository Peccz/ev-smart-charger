import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import math
import json
import os
import dateutil.parser
import logging
from config_manager import SETTINGS_PATH, OVERRIDES_PATH

logger = logging.getLogger(__name__)

class Optimizer:
    def __init__(self, config):
        self.config = config
        self.buffer_threshold_price = config['optimization']['price_buffer_threshold']
        # Use absolute paths from ConfigManager
        self.settings_path = SETTINGS_PATH
        self.overrides_path = OVERRIDES_PATH

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
        Includes diurnal cycles (morning/evening peaks) and wind adjustments.
        """
        now = datetime.now()
        forecast_end_time = now + timedelta(days=forecast_horizon_days)
        
        # Convert official prices to DataFrame
        official_prices_df = pd.DataFrame(current_prices)
        if not official_prices_df.empty:
            official_prices_df['time_start'] = pd.to_datetime(official_prices_df['time_start'], utc=True).dt.tz_convert('Europe/Berlin').dt.tz_localize(None)
            official_prices_df = official_prices_df.set_index('time_start')
            official_prices_df = official_prices_df.resample('1h').mean()
        
        # Calculate a realistic base price from recent official data or fallback
        base_price_sek = official_prices_df['price_sek'].mean() if not official_prices_df.empty else 0.5

        # --- Diurnal Profiles (Hourly Multipliers) ---
        # 00-23 index
        weekday_profile = [
            0.60, 0.55, 0.50, 0.55, 0.65, 0.80, # 00-05 (Night dip)
            1.10, 1.40, 1.50, 1.30, 1.20, 1.10, # 06-11 (Morning peak)
            1.05, 1.00, 1.00, 1.10, 1.20, 1.50, # 12-17 (Day/Afternoon start)
            1.60, 1.50, 1.30, 1.10, 0.90, 0.75  # 18-23 (Evening peak -> Night)
        ]
        
        weekend_profile = [
            0.65, 0.60, 0.55, 0.55, 0.60, 0.65, # 00-05 (Night dip, flatter)
            0.70, 0.80, 0.90, 1.00, 1.05, 1.05, # 06-11 (Slow rise)
            1.00, 0.95, 0.90, 0.95, 1.05, 1.20, # 12-17 (Day)
            1.30, 1.25, 1.15, 1.05, 0.95, 0.80  # 18-23 (Evening peak, smaller)
        ]

        all_forecast_prices = []

        # If no weather forecast, return official prices only
        if not weather_forecast:
            logger.warning("Optimizer: No weather forecast data, returning official prices only")
            if not official_prices_df.empty:
                official_prices_df_reset = official_prices_df.reset_index()
                official_prices_df_reset['time_start'] = official_prices_df_reset['time_start'].apply(lambda x: x.isoformat())
                official_prices_df_reset['source'] = 'Official'
                return official_prices_df_reset.to_dict(orient='records')
            return []

        for hour_data in weather_forecast:
            hour_time = pd.to_datetime(hour_data['time'])
            
            if hour_time < now.replace(minute=0, second=0, microsecond=0):
                continue
            
            # If we have an official price, use it
            if hour_time in official_prices_df.index:
                all_forecast_prices.append({
                    "time_start": hour_time,
                    "price_sek": official_prices_df.loc[hour_time]['price_sek'],
                    "source": "Official"
                })
                continue

            if hour_time > forecast_end_time:
                continue
            
            # --- FORECAST GENERATION (Fundamental Model) ---
            
            # 1. Wind Factor (High wind = Low price)
            wind_speed = hour_data.get('wind_kmh_80m', 10)
            wind_factor = 1.0
            if wind_speed < 10:
                wind_factor = 1.0 + (10 - wind_speed) * 0.03 # +3% per km/h below 10
            elif wind_speed > 25:
                wind_factor = max(0.7, 1.0 - (wind_speed - 25) * 0.015) # -1.5% per km/h above 25, max -30%

            # 2. Solar Factor (High sun = Low price)
            solar_rad = hour_data.get('solar_w_m2', 0)
            solar_factor = 1.0
            if solar_rad > 100:
                # Reduce price up to 15% at full sun (e.g. 800 W/m2)
                reduction = min(0.15, (solar_rad - 100) * 0.0002)
                solar_factor = 1.0 - reduction

            # 3. Temperature/Demand Factor (Low temp = High price)
            temp = hour_data.get('temp_c', 10)
            temp_factor = 1.0
            if temp < 5:
                # Increase price as it gets colder
                # e.g. at -10C: (5 - (-10)) * 0.02 = 15 * 0.02 = +30%
                temp_factor = 1.0 + (5 - temp) * 0.02 
            
            # 4. Seasonal Factor (Month based approximation of hydro/demand)
            month = hour_time.month
            seasonal_factor = 1.0
            if month in [12, 1, 2]:   seasonal_factor = 1.15 # Winter (High demand, low hydro flow)
            elif month in [5, 6]:     seasonal_factor = 0.85 # Spring flood (High hydro)
            elif month in [7, 8]:     seasonal_factor = 0.90 # Summer (Low demand)
            elif month in [10, 11]:   seasonal_factor = 1.05 # Late Autumn (Increasing demand)

            # 5. Diurnal/Time Factor (Consumption profile)
            is_weekend = hour_time.weekday() >= 5
            hour_idx = hour_time.hour
            time_factor = weekend_profile[hour_idx] if is_weekend else weekday_profile[hour_idx]

            # Calculate final price
            forecasted_price_sek = base_price_sek * wind_factor * solar_factor * temp_factor * seasonal_factor * time_factor
            
            # Sanity limits (ensure we don't go crazy)
            forecasted_price_sek = max(0.05, min(forecasted_price_sek, 8.0))
            
            all_forecast_prices.append({
                "time_start": hour_time,
                "price_sek": forecasted_price_sek,
                "source": "Forecasted"
            })
        
        # Sort and clean
        full_price_df = pd.DataFrame(all_forecast_prices)
        if not full_price_df.empty:
            full_price_df = full_price_df.drop_duplicates(subset=['time_start'], keep='first')
            full_price_df = full_price_df.sort_values(by='time_start')
            full_price_df['time_start'] = full_price_df['time_start'].apply(lambda x: x.isoformat())
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

    def _calculate_dynamic_target(self, vehicle_id, prices):
        """
        Calculates the dynamic target SoC based on current price vs long-term average.
        Returns (target_soc, mode_string)
        """
        user_settings = self._get_user_settings()
        
        # Get constraints
        min_soc = user_settings.get(f"{vehicle_id}_min_soc", 40)
        max_soc = user_settings.get(f"{vehicle_id}_max_soc", 80) # Default max same as old target default
        
        if not prices:
            return max_soc, "Fallback (No Data)"

        # Calculate price stats
        df = pd.DataFrame(prices)
        
        # Long term average (entire forecast horizon)
        long_term_avg = df['price_sek'].mean()
        
        # Short term average (next 12 hours, representing "immediate future")
        short_term_df = df.head(12)
        short_term_avg = short_term_df['price_sek'].mean()
        
        # Determine strategy
        # If short term is significantly cheaper (>15%) than long term -> Charge to MAX
        # If short term is significantly more expensive (>15%) -> Charge to MIN
        # Otherwise -> Linear interpolation
        
        ratio = short_term_avg / long_term_avg if long_term_avg > 0 else 1.0
        
        if ratio < 0.85:
            return max_soc, "Aggressive (Cheap)"
        elif ratio > 1.15:
            return min_soc, "Conservative (Expensive)"
        else:
            # Linear interpolation between 0.85 (Max) and 1.15 (Min)
            # Map ratio 0.85..1.15 to Max..Min
            factor = (ratio - 0.85) / (1.15 - 0.85) # 0.0 at 0.85, 1.0 at 1.15
            dynamic_soc = max_soc - (factor * (max_soc - min_soc))
            return int(dynamic_soc), "Balanced"

    def suggest_action(self, vehicle, prices, weather_forecast):
        # 0. Check Manual Overrides
        overrides = self._get_overrides()
        vehicle_id = "mercedes_eqv" if "Mercedes" in vehicle.name else "nissan_leaf"

        if vehicle_id in overrides:
            ovr = overrides[vehicle_id]
            logger.info(f"Manual override active for {vehicle_id}: {ovr['action']} (expires: {ovr['expires_at']})")
            if ovr['action'] == "CHARGE":
                return {"action": "CHARGE", "reason": "Manual Override (Ladda Nu!)"}
            if ovr['action'] == "STOP":
                return {"action": "IDLE", "reason": "Manual Override (Stoppa)"}

        status = vehicle.get_status()
        current_soc = status['soc']
        
        # 1. Calculate Dynamic Target SoC
        target_soc, mode = self._calculate_dynamic_target(vehicle_id, prices)
        
        # Also keep the old "buffer" logic as a safety override if extreme weather
        if self._should_buffer(prices, weather_forecast):
            target_soc = max(target_soc, 95) # Force high target if storm incoming
            mode = "Storm Buffering"

        # Daily Charging Logic: Always aim to charge at least once per day
        # This ensures battery health and readiness
        user_settings = self._get_user_settings()
        daily_charging = user_settings.get('daily_charging_enabled', True)  # Default: enabled

        if current_soc >= target_soc and not daily_charging:
            return {"action": "IDLE", "reason": f"Target SoC {target_soc}% reached ({mode})"}

        # If daily charging enabled and target reached, still check if we should top-up during cheap hours
        if current_soc >= target_soc:
            # Only charge further if price is in bottom 25% AND plugged in
            if not status['plugged_in']:
                return {"action": "IDLE", "reason": f"Target {target_soc}% reached, not plugged in"}

            if prices:
                df = pd.DataFrame(prices)
                current_price = df.iloc[0]['price_sek'] if len(df) > 0 else 999
                percentile_25 = df['price_sek'].quantile(0.25)

                if current_price <= percentile_25:
                    return {"action": "CHARGE", "reason": f"Daily top-up: Current price {current_price:.2f} SEK in bottom 25% (target {target_soc}% reached)"}

            return {"action": "IDLE", "reason": f"Target SoC {target_soc}% reached ({mode})"}

        # 2. Calculate Energy Needs
        capacity_kwh = vehicle.capacity_kwh
        charge_speed_kw = vehicle.max_charge_kw
        
        soc_needed_percent = target_soc - current_soc
        kwh_needed = (soc_needed_percent / 100.0) * capacity_kwh
        hours_needed = math.ceil(kwh_needed / charge_speed_kw)
        
        # 3. Basic checks
        if not status['plugged_in']:
            return {"action": "IDLE", "reason": f"Vehicle not plugged in. Target: {target_soc}% ({mode})"}

        if hours_needed <= 0:
             return {"action": "IDLE", "reason": "Calculation error: 0 hours needed"}

        # 4. Analyze Prices (Planning Horizon)
        if not prices:
            logger.warning("Optimizer: No price data. Failsafe charging enabled.")
            return {"action": "CHARGE", "reason": "No price data, failsafe charging"}

        df = pd.DataFrame(prices)
        
        if len(df) < hours_needed:
             logger.warning(f"Optimizer: Not enough price data ({len(df)}h) to plan {hours_needed}h. Failsafe charging enabled.")
             return {"action": "CHARGE", "reason": "Not enough price data, failsafe charging"}

        df_sorted = df.sort_values(by='price_sek', ascending=True)
        cheapest_hours = df_sorted.head(hours_needed)['time_start'].tolist()
        
        current_time_start = df.iloc[0]['time_start']
        
        if current_time_start in cheapest_hours:
            current_price = df.iloc[0]['price_sek']
            return {
                "action": "CHARGE", 
                "reason": f"{mode}: Charging to {target_soc}%. Current price ({current_price:.2f} SEK) is optimal."
            }

        next_best_price = df_sorted.head(hours_needed)['price_sek'].max()
        return {
            "action": "IDLE", 
            "reason": f"{mode}: Target {target_soc}%. Waiting for < {next_best_price:.2f} SEK. Current: {df.iloc[0]['price_sek']:.2f} SEK."
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
