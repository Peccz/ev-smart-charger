from flask import Flask, render_template, jsonify, request, redirect, url_for
import json
import os
import math
from datetime import datetime, timedelta
import pandas as pd
import yaml # Import yaml to load config/settings.yaml
import requests # Needed for HomeAssistantClient
# import pycarwings2 # Not needed, Kamereon client is used by vehicles.py

from connectors.spot_price import SpotPriceService
from connectors.weather import WeatherService
from optimizer.engine import Optimizer # Import Optimizer to generate price forecast
from connectors.vehicles import MercedesEQV, NissanLeaf # Import NissanLeaf directly

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
app.secret_key = "super_secret_key_change_me" 

SETTINGS_PATH = "data/user_settings.json"
OVERRIDES_PATH = "data/manual_overrides.json"
STATE_PATH = "data/optimizer_state.json"
MANUAL_STATUS_PATH = "data/manual_status.json"
YAML_CONFIG_PATH = "config/settings.yaml"
FORECAST_HISTORY_FILE = "data/forecast_history.json" # Added

DEFAULT_SETTINGS = {
    "mercedes_eqv_min_soc": 40, # New default keys
    "mercedes_eqv_max_soc": 80,
    "nissan_leaf_min_soc": 40,
    "nissan_leaf_max_soc": 80,
    "departure_time": "07:00",
    "smart_buffering": True, # Still present, but the new logic mostly replaces it.
    "ha_url": "http://100.100.118.62:8123",
    "ha_token": "",
    "ha_merc_soc_entity_id": "",
    "ha_merc_plugged_entity_id": ""
}

spot_service = SpotPriceService()
weather_service = WeatherService(59.5196, 17.9285)

def get_settings():
    if not os.path.exists(SETTINGS_PATH):
        return DEFAULT_SETTINGS
    try:
        with open(SETTINGS_PATH, 'r') as f:
            current_settings = json.load(f)
            # Merge with defaults to ensure new fields exist.
            # Handle potential old keys for migration:
            if 'mercedes_target' in current_settings and 'mercedes_eqv_max_soc' not in current_settings:
                current_settings['mercedes_eqv_max_soc'] = current_settings['mercedes_target']
            if 'nissan_target' in current_settings and 'nissan_leaf_max_soc' not in current_settings:
                current_settings['nissan_leaf_max_soc'] = current_settings['nissan_target']
            # Migrate old min/max if they exist under the wrong keys
            if 'mercedes_min_soc' in current_settings and 'mercedes_eqv_min_soc' not in current_settings:
                current_settings['mercedes_eqv_min_soc'] = current_settings['mercedes_min_soc']
            if 'mercedes_max_soc' in current_settings and 'mercedes_eqv_max_soc' not in current_settings:
                current_settings['mercedes_eqv_max_soc'] = current_settings['mercedes_max_soc']
            if 'nissan_min_soc' in current_settings and 'nissan_leaf_min_soc' not in current_settings:
                current_settings['nissan_leaf_min_soc'] = current_settings['nissan_min_soc']
            if 'nissan_max_soc' in current_settings and 'nissan_leaf_max_soc' not in current_settings:
                current_settings['nissan_leaf_max_soc'] = current_settings['nissan_max_soc']


            return {**DEFAULT_SETTINGS, **current_settings}
    except Exception as e:
        app.logger.error(f"Error loading user_settings.json: {e}")
        return DEFAULT_SETTINGS

def _load_forecast_history():
    """Loads historical price forecasts from file."""
    if not os.path.exists(FORECAST_HISTORY_FILE):
        return {}
    try:
        with open(FORECAST_HISTORY_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        app.logger.warning(f"Could not decode {FORECAST_HISTORY_FILE}, returning empty history.")
        return {}
    except Exception as e:
        app.logger.error(f"Error loading forecast history: {e}")
        return {}

# --- CONFIGURATION LOADING FOR OPTIMIZER INSTANCE (USED BY WEBAPP) ---
# This is a function to ensure it loads the complete config
def _load_full_config_for_optimizer():
    full_config = {}
    if os.path.exists(YAML_CONFIG_PATH):
        try:
            with open(YAML_CONFIG_PATH, 'r') as f:
                full_config = yaml.safe_load(f)
        except Exception as e:
            app.logger.error(f"Error loading base config for Optimizer in web_app: {e}")
    
    user_settings = get_settings()

    # Ensure 'optimization' key exists even if config is minimal
    if 'optimization' not in full_config:
        full_config['optimization'] = {'price_buffer_threshold': 0.10, 'planning_horizon_days': 3}
    
    # Ensure 'cars' structure
    if 'cars' not in full_config:
        full_config['cars'] = {}
        
    # Mercedes Config Merge
    merc_base = full_config['cars'].get('mercedes_eqv', {})
    full_config['cars']['mercedes_eqv'] = {
        'capacity_kwh': merc_base.get('capacity_kwh', 90),
        'max_charge_kw': merc_base.get('max_charge_kw', 11),
        'vin': merc_base.get('vin'),
        'target_soc': user_settings.get('mercedes_eqv_target', user_settings.get('mercedes_target', merc_base.get('target_soc', 80))),
        'min_soc': user_settings.get('mercedes_eqv_min_soc', 40),
        'max_soc': user_settings.get('mercedes_eqv_max_soc', 80),
        'ha_url': user_settings.get('ha_url'),
        'ha_token': user_settings.get('ha_token'),
        'ha_merc_soc_entity_id': user_settings.get('ha_merc_soc_entity_id'),
        'ha_merc_plugged_entity_id': user_settings.get('ha_merc_plugged_entity_id')
    }

    # Nissan Config Merge
    nis_base = full_config['cars'].get('nissan_leaf', {})
    full_config['cars']['nissan_leaf'] = {
        'capacity_kwh': nis_base.get('capacity_kwh', 40),
        'max_charge_kw': nis_base.get('max_charge_kw', 6.6),
        'vin': user_settings.get('nissan_vin', nis_base.get('vin')),
        'target_soc': user_settings.get('nissan_leaf_target', user_settings.get('nissan_target', nis_base.get('target_soc', 80))),
        'min_soc': user_settings.get('nissan_leaf_min_soc', 40),
        'max_soc': user_settings.get('nissan_leaf_max_soc', 80),
        'ha_url': user_settings.get('ha_url'),
        'ha_token': user_settings.get('ha_token'),
        'ha_nissan_soc_entity_id': user_settings.get('ha_nissan_soc_entity_id'),
        'ha_nissan_plugged_entity_id': user_settings.get('ha_nissan_plugged_entity_id'),
        'ha_nissan_range_entity_id': user_settings.get('ha_nissan_range_entity_id')
    }

    return full_config

optimizer_instance = Optimizer(_load_full_config_for_optimizer())
# --- END CONFIGURATION LOADING ---

def save_settings(settings):
    with open(SETTINGS_PATH, 'w') as f:
        json.dump(settings, f, indent=2)

def get_overrides():
    if not os.path.exists(OVERRIDES_PATH):
        return {}
    try:
        with open(OVERRIDES_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        app.logger.error(f"Error loading overrides.json: {e}")
        return {}

def set_override(vehicle_id, action, duration_minutes=60):
    overrides = get_overrides()
    if action == "AUTO":
        if vehicle_id in overrides:
            del overrides[vehicle_id]
    else:
        expiry = datetime.now() + timedelta(minutes=duration_minutes)
        overrides[vehicle_id] = {
            "action": action,
            "expires_at": expiry.isoformat()
        }
    with open(OVERRIDES_PATH, 'w') as f:
        json.dump(overrides, f, indent=2)

def get_manual_status():
    if not os.path.exists(MANUAL_STATUS_PATH):
        return {}
    try:
        with open(MANUAL_STATUS_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        app.logger.error(f"Error loading manual_status.json: {e}")
        return {}

def set_manual_soc(vehicle_id, soc):
    status = get_manual_status()
    status[vehicle_id] = {
        "soc": soc,
        "updated_at": datetime.now().isoformat()
    }
    with open(MANUAL_STATUS_PATH, 'w') as f:
        json.dump(status, f, indent=2)

def get_optimizer_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        app.logger.error(f"Error loading optimizer_state.json: {e}")
        return {}


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/planning')
def planning_page():
    return render_template('planning.html')

@app.route('/settings')
def settings_page():
    return render_template('settings.html')

@app.route('/api/status')
def api_status():
    settings = get_settings()
    overrides = get_overrides()
    state = get_optimizer_state()
    manual_status = get_manual_status() # Always load manual status
    
    # Initialize Optimizer and fetch prices for dynamic target calculation
    full_merged_config = _load_full_config_for_optimizer() # Use the new loader
    optimizer = Optimizer(full_merged_config)
    official_prices = spot_service.get_prices_upcoming()
    weather_forecast = weather_service.get_forecast()
    prices_with_forecast = optimizer._generate_price_forecast(official_prices, weather_forecast)
    
    cars = []
    for k, v in state.items():
        v['name'] = k
        cars.append(v)
    cars.sort(key=lambda x: x.get('urgency_score', 0), reverse=True)
    
    priority_car_id = None
    if cars and cars[0].get('urgency_score', 0) > 0:
        priority_car_id = cars[0]['id']

    cars_data = {}
    
    def build_car(name, key_id): # Removed target_key as target is now dynamic
        car_state = state.get(name, {}) # This is the source from optimizer_state.json
        
        # Prioritize SOC from optimizer_state.json
        soc = car_state.get('soc', 0) # Default to 0 if not found in optimizer state
        
        # If optimizer_state has 0% (or mock 45% if we used that), then use manual value
        # if the manual value is different and more recent.
        manual_val_data = manual_status.get(key_id, {})
        manual_soc = manual_val_data.get('soc')
        manual_updated_at_str = manual_val_data.get('updated_at')
        
        # Decide which SOC to display in UI and use for logic
        display_soc = soc 
        display_manual_soc = manual_soc if manual_soc is not None else soc
        
        # Logic to use manual_soc if optimizer_state is 0 and manual is available
        # or if optimizer_state is outdated compared to manual
        if manual_soc is not None:
            optimizer_updated_at_str = car_state.get('last_updated')
            
            # Compare update times if both are available
            if manual_updated_at_str and optimizer_updated_at_str:
                manual_updated_at = datetime.fromisoformat(manual_updated_at_str)
                optimizer_updated_at = datetime.fromisoformat(optimizer_updated_at_str)
                if manual_updated_at > optimizer_updated_at and soc == 0: # Use manual if newer AND optimizer is 0
                    display_soc = manual_soc
                elif soc == 0 and manual_soc is not None: # If optimizer reports 0, but manual has something
                    display_soc = manual_soc
            elif soc == 0 and manual_soc is not None: # If optimizer reports 0 and manual has a value (no timestamps to compare)
                display_soc = manual_soc

        # Dynamically calculate the target SoC for display
        dynamic_target_soc, current_mode = optimizer._calculate_dynamic_target(key_id, prices_with_forecast)
        
        # Now, fetch other details from car_state or settings
        # target = settings.get(target_key, 80) # No longer needed, using dynamic_target_soc
        min_soc = settings.get(f"{key_id}_min_soc", 40)
        max_soc = settings.get(f"{key_id}_max_soc", 80)

        plugged_in = car_state.get('plugged_in', False)
        urgency = car_state.get('urgency_score', 0)
        
        is_priority = (key_id == priority_car_id)
        needs_plugging = False
        urgency_msg = ""
        swap_msg = ""
        
        if is_priority and not plugged_in and urgency > 0:
            needs_plugging = True
            urgency_msg = "Denna bil MÅSTE laddas nu!"
            other_car = cars[1] if len(cars) > 1 and cars[0]['id'] == key_id else cars[0]
            if other_car.get('plugged_in'):
                swap_msg = f"Koppla ur {other_car.get('name', 'den andra bilen')}!"

        if not is_priority and plugged_in and priority_car_id and priority_car_id != key_id:
             p_car = next((c for c in cars if c['id'] == priority_car_id), None)
             if p_car and not p_car.get('plugged_in'):
                 needs_plugging = True 
                 urgency_msg = "Var god koppla ur denna bil."
                 swap_msg = f"Byt till {p_car.get('name')}!"
                 
        start_time_text = ""
        if plugged_in and car_state.get('action') == 'IDLE' and urgency > 0:
             start_time_text = "Startar senare..."

        # --- UI CONSISTENCY CHECK ---
        # If settings changed recently, the stored state might say "Target reached" (e.g. 40%)
        # but the new dynamic target is higher (e.g. 60%). This looks like a bug.
        # We detect this mismatch and display a "Pending" message instead.
        display_action = car_state.get('action', 'IDLE')
        display_reason = car_state.get('reason', '-')
        
        if display_soc < dynamic_target_soc and "reached" in str(display_reason):
            display_action = "PENDING"
            display_reason = "Mål ändrat. Inväntar nästa beräkning..."
            # Also clear start time text as it might be invalid
            start_time_text = ""

        return {
            "name": name,
            "id": key_id,
            "soc": display_soc, # Use the determined display_soc
            "manual_soc": display_manual_soc, # Ensure UI slider shows something reasonable
            "target": dynamic_target_soc, # THIS IS THE DYNAMICALLY CALCULATED TARGET
            "target_mode": current_mode, # Pass the mode for future use if needed
            "min_soc": min_soc,
            "max_soc": max_soc,
            "plugged_in": plugged_in,
            "override": overrides.get(key_id),
            "action": display_action,
            "reason": display_reason,
            "urgency_score": urgency,
            "is_priority": is_priority,
            "needs_plugging": needs_plugging,
            "urgency_msg": urgency_msg,
            "swap_msg": swap_msg,
            "start_time_text": start_time_text
        }

    cars_data['mercedes'] = build_car("Mercedes EQV", "mercedes_eqv")
    cars_data['nissan'] = build_car("Nissan Leaf", "nissan_leaf")
    
    return jsonify({
        "cars": cars_data,
        "system": {
            "departure": settings.get('departure_time', '07:00')
        }
    })

@app.route('/api/plan')
def api_plan():
    try:
        # Reload full config for optimizer with latest user settings
        full_merged_config = _load_full_config_for_optimizer() # Use the new loader
        optimizer = Optimizer(full_merged_config)

        official_prices = spot_service.get_prices_upcoming()
        weather_forecast = weather_service.get_forecast()
        
        # Generate full price forecast (official + estimated)
        prices_with_forecast = optimizer._generate_price_forecast(official_prices, weather_forecast)

        df = pd.DataFrame(prices_with_forecast)
        analysis = []
        charging_plan = [] 
        
        # The optimizer_state will tell us WHICH car is priority and what its plan is
        state = get_optimizer_state()
        cars_in_state = []
        for k, v in state.items():
            v['name'] = k
            cars_in_state.append(v)
        cars_in_state.sort(key=lambda x: x.get('urgency_score', 0), reverse=True)
        
        priority_car_from_state = cars_in_state[0] if cars_in_state else None
        
        if priority_car_from_state and priority_car_from_state.get('urgency_score', 0) > 0:
            # We need to re-run the planning to get the specific hours for the UI
            # This is duplicating logic but ensures UI matches current config.
            
            # Simulate getting the car object (need full config for that)
            # Rerunning load_config here for the car objects
            full_merged_config = _load_full_config_for_optimizer() # Reload config, now it will include merged user settings
            if priority_car_from_state['id'] == 'mercedes_eqv':
                car_obj = MercedesEQV(full_merged_config['cars']['mercedes_eqv'])
            else: # nissan_leaf
                car_obj = NissanLeaf(full_merged_config['cars']['nissan_leaf'])
            
            # This is a bit of a hack, calling job() logic parts here, but needed for UI.
            # In a perfect world, optimizer_state would contain the actual schedule.
            current_car_status = car_obj.get_status()
            
            # Calculate dynamic target SoC using the same logic as the engine
            target_soc, mode = optimizer._calculate_dynamic_target(priority_car_from_state['id'], prices_with_forecast)
            
            # Get min/max from settings for display
            settings = get_settings()
            min_soc = settings.get(f"{priority_car_from_state['id']}_min_soc", 40)
            max_soc = settings.get(f"{priority_car_from_state['id']}_max_soc", 80)

            # Recalculate based on current values and dynamic target
            soc_needed_percent = target_soc - current_car_status['soc']
            kwh_needed = (soc_needed_percent / 100.0) * car_obj.capacity_kwh
            hours_needed = math.ceil(kwh_needed / car_obj.max_charge_kw)
            
            analysis.append(f"Målstrategi: <b>{mode}</b>")
            analysis.append(f"Intervall: {min_soc}% - {max_soc}%")
            analysis.append(f"Valt mål: <b>{target_soc}%</b>")

            if hours_needed > 0:
                df_prices_with_forecast = pd.DataFrame(prices_with_forecast)
                df_sorted = df_prices_with_forecast.sort_values(by='price_sek', ascending=True)
                cheapest_hours = df_sorted.head(hours_needed)['time_start'].tolist()
                
                for p in prices_with_forecast:
                    is_charging = 1 if p['time_start'] in cheapest_hours else 0
                    charging_plan.append(is_charging)
                
                start_time = min(cheapest_hours) if cheapest_hours else "-"
                start_time_fmt = datetime.fromisoformat(start_time).strftime("%H:%M") if cheapest_hours else "-"
                analysis.append(f"Planerar laddning för {priority_car_from_state['name']}.")
                analysis.append(f"Behov: {hours_needed} timmar.")
                analysis.append(f"Starttid: {start_time_fmt}.")
                analysis.append(f"Valde billigaste timmarna (Snitt: {df_sorted.head(hours_needed)['price_sek'].mean():.2f} kr).")
            else:
                charging_plan = [0] * len(prices_with_forecast)
                analysis.append(f"Inget laddbehov just nu för {priority_car_from_state['name']} (Mål {target_soc}% uppnått).")
        else:
            charging_plan = [0] * len(prices_with_forecast)
            analysis.append("Inget laddbehov just nu.")

        # --- FORECAST BACKTESTING / FACIT ---
        analysis.append("<hr>")
        analysis.append("<h6>🎯 Prognos Facit (Igår)</h6>")
        
        forecast_history = _load_forecast_history()
        yesterday = datetime.now() - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y-%m-%d")
        
        if yesterday_str in forecast_history:
            forecast_data_yesterday = forecast_history[yesterday_str]
            actual_prices_yesterday = spot_service.get_prices(yesterday) # Get actual prices for yesterday
            
            if actual_prices_yesterday and forecast_data_yesterday:
                df_forecast = pd.DataFrame(forecast_data_yesterday)
                df_actual = pd.DataFrame(actual_prices_yesterday)

                # Convert time_start to datetime for easy comparison and merging
                df_forecast['time_start'] = pd.to_datetime(df_forecast['time_start'])
                df_actual['time_start'] = pd.to_datetime(df_actual['time_start'])
                
                # Resample actual prices to hourly to match forecast (if spot service returns 15min)
                df_actual = df_actual.set_index('time_start').resample('1h').mean().reset_index()

                # Merge on time_start
                df_compare = pd.merge(df_forecast, df_actual, on='time_start', suffixes=('_forecast', '_actual'))
                
                if not df_compare.empty:
                    df_compare['abs_diff'] = abs(df_compare['price_sek_forecast'] - df_compare['price_sek_actual'])
                    
                    avg_abs_diff = df_compare['abs_diff'].mean()
                    forecast_avg = df_compare['price_sek_forecast'].mean()
                    actual_avg = df_compare['price_sek_actual'].mean()

                    analysis.append(f"Prognos från {yesterday_str} (Medel: {forecast_avg:.2f} kr)")
                    analysis.append(f"Faktiskt pris igår (Medel: {actual_avg:.2f} kr)")
                    analysis.append(f"Genomsnittlig avvikelse: {avg_abs_diff:.2f} kr")
                else:
                    analysis.append("Inga matchande timmar för jämförelse igår.")
            else:
                analysis.append("Kunde inte hämta faktiska priser eller historisk prognos för igår.")
        else:
            analysis.append(f"Ingen historisk prognos sparad för {yesterday_str}.")
        # --- END FACIT ---

        return jsonify({
            "prices": prices_with_forecast,
            "plan": charging_plan,
            "weather": weather_forecast,
            "analysis": analysis
        })
    except Exception as e:
        app.logger.error(f"Error in api_plan: {e}")
        return jsonify({"error": str(e)})

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'POST':
        data = request.json
        app.logger.info(f"Saving settings: {data}")
        current = get_settings()
        current.update(data)
        save_settings(current)
        return jsonify({"status": "ok"})
    else:
        return jsonify(get_settings())

@app.route('/api/override', methods=['POST'])
def api_override():
    data = request.json
    set_override(data.get('vehicle_id'), data.get('action'), data.get('duration', 60))
    return jsonify({"status": "ok"})

@app.route('/api/manual_soc', methods=['POST'])
def api_manual_soc():
    data = request.json
    set_manual_soc(data.get('vehicle_id'), int(data.get('soc')))
    return jsonify({"status": "ok"})

@app.route('/api/nissan/debug_login')
def nissan_debug_login():
    try:
        user_settings = get_settings() # This will load from user_settings.json
        
        # Simulate loading full config as main.py does
        full_config = {}
        if os.path.exists(YAML_CONFIG_PATH):
            with open(YAML_CONFIG_PATH, 'r') as f:
                full_config = yaml.safe_load(f)
        
        # Inject Nissan credentials from user_settings
        nissan_config_for_test = full_config['cars'].get('nissan_leaf', {})
        nissan_config_for_test['username'] = user_settings.get('nissan_username', nissan_config_for_test.get('username'))
        nissan_config_for_test['password'] = user_settings.get('nissan_password', nissan_config_for_test.get('password'))
        nissan_config_for_test['vin'] = user_settings.get('nissan_vin', nissan_config_for_test.get('vin'))

        nissan_leaf_test = NissanLeaf(nissan_config_for_test)
        
        # Attempt login
        login_successful = nissan_leaf_test._login()
        
        if login_successful:
            return jsonify({"status": "Login successful", "message": "Successfully obtained Nissan Leaf object."})
        else:
            return jsonify({"status": "Login failed", "message": "Check username/password or API changes."})
            
    except Exception as e:
        app.logger.error(f"Error in nissan_debug_login: {e}")
        return jsonify({"status": "Error", "message": str(e)})

if __name__ == '__main__':
    os.makedirs("data", exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)