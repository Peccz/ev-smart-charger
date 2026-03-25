from flask import Flask, render_template, jsonify, request, redirect, url_for
import json
import os
import math
import logging
from datetime import datetime, timedelta
import pandas as pd
import yaml
import requests

from config_manager import (ConfigManager, FORECAST_HISTORY_FILE,
                            OVERRIDES_PATH, STATE_PATH, MANUAL_STATUS_PATH, DATABASE_PATH)
from database.db_manager import DatabaseManager
from connectors.spot_price import SpotPriceService
from connectors.weather import WeatherService
from optimizer.engine import Optimizer
from connectors.vehicles import MercedesEQV

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
app.secret_key = ConfigManager.get_flask_secret_key()

spot_service = SpotPriceService()
_startup_config = ConfigManager.load_full_config()
weather_service = WeatherService(
    _startup_config['location']['latitude'],
    _startup_config['location']['longitude']
)

def get_optimizer_state():
    if not STATE_PATH.exists():
        return {}
    try:
        with open(STATE_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def get_manual_status():
    if not MANUAL_STATUS_PATH.exists():
        return {}
    try:
        with open(MANUAL_STATUS_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def get_overrides():
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        with open(OVERRIDES_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        app.logger.error(f"Error loading overrides: {e}")
        return {}

def set_override(vehicle_id, action, duration_minutes=60):
    overrides = get_overrides()
    if action == "AUTO":
        overrides.pop(vehicle_id, None)
    else:
        expiry = datetime.now() + timedelta(minutes=duration_minutes)
        overrides[vehicle_id] = {
            "action": action,
            "expires_at": expiry.isoformat()
        }
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OVERRIDES_PATH, 'w') as f:
        json.dump(overrides, f, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/planning')
def planning_page():
    return render_template('planning.html')

@app.route('/cars')
def cars_page():
    return render_template('cars.html')

@app.route('/settings')
def settings():
    return render_template('settings.html')

@app.route('/history')
def history():
    return render_template('history.html')

@app.route('/api/status')
def api_status():
    try:
        settings = ConfigManager.get_settings()
        state = get_optimizer_state()
        manual_status = get_manual_status()
        
        full_merged_config = ConfigManager.load_full_config()
        optimizer = Optimizer(full_merged_config)
        
        official_prices = spot_service.get_prices_upcoming()
        historical_avg = spot_service.get_historical_average(days=7)
        optimizer.long_term_history_avg = historical_avg
        
        weather_forecast = weather_service.get_forecast()
        prices_with_forecast = optimizer._generate_price_forecast(official_prices, weather_forecast)
        
        def build_car(name, key_id): 
            car_state = state.get(name)
            if not car_state: return None
                
            soc = car_state.get('soc', 0)
            manual_val = manual_status.get(key_id, {}).get('soc')
            display_soc = manual_val if (manual_val is not None and soc == 0) else soc

            dynamic_target_soc, current_mode = optimizer._calculate_dynamic_target(key_id, prices_with_forecast)
            
            # Fetch min/max from settings
            min_soc = settings.get(f"{key_id}_min_soc", 40)
            max_soc = settings.get(f"{key_id}_max_soc", 80)

            return {
                "name": name,
                "id": key_id,
                "soc": display_soc, 
                "target": dynamic_target_soc,
                "target_mode": current_mode,
                "min_soc": min_soc,
                "max_soc": max_soc,
                "plugged_in": car_state.get('plugged_in', False),
                "range_km": car_state.get('range_km', 0),
                "action": car_state.get('action', 'IDLE'),
                "reason": car_state.get('reason', '-'),
                "urgency_score": car_state.get('urgency_score', 0)
            }

        cars_data = {}
        merc_data = build_car("Mercedes EQV", "mercedes_eqv")
        if merc_data: cars_data['mercedes'] = merc_data
        
        return jsonify({
            "cars": cars_data,
            "system": {
                "departure": settings.get('departure_time', '07:00'),
                "guard_msg": state.get('guard_msg', "")
            }
        })
    except Exception as e:
        app.logger.error(f"Error in api_status: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/plan')
def api_plan():
    try:
        full_merged_config = ConfigManager.load_full_config()
        optimizer = Optimizer(full_merged_config)
        official_prices = spot_service.get_prices_upcoming()
        historical_avg = spot_service.get_historical_average(days=7)
        optimizer.long_term_history_avg = historical_avg
        weather_forecast = weather_service.get_forecast()
        prices_with_forecast = optimizer._generate_price_forecast(official_prices, weather_forecast)

        if not prices_with_forecast:
             return jsonify({"prices": [], "plan": [], "weather": [], "analysis": ["Ingen prisdata tillgänglig."] })

        state = get_optimizer_state()
        manual_status = get_manual_status()
        merc_state = state.get("Mercedes EQV", {})
        
        car_cfg = full_merged_config['cars']['mercedes_eqv']
        car_obj = MercedesEQV(car_cfg)
        
        current_soc = merc_state.get('soc', 0)
        manual_soc = manual_status.get('mercedes_eqv', {}).get('soc')
        if current_soc == 0 and manual_soc is not None:
            current_soc = manual_soc
        
        target_soc, mode = optimizer._calculate_dynamic_target("mercedes_eqv", prices_with_forecast)
        min_soc = car_cfg.get('min_soc', 40)
        
        soc_needed = target_soc - current_soc
        capacity = car_cfg.get('capacity_kwh', 90)
        charge_speed = merc_state.get('learned_speed', car_cfg.get('max_charge_kw', 11))
        if charge_speed <= 0: charge_speed = 11
        
        kwh_needed = (max(0, soc_needed) / 100.0) * capacity
        hours_needed = math.ceil(kwh_needed / charge_speed)
        
        df_prices = pd.DataFrame(prices_with_forecast)
        df_prices['time_start_dt'] = pd.to_datetime(df_prices['time_start'])
        deadline = optimizer.get_deadline()
        
        cheapest_hours = []
        if hours_needed > 0:
            if current_soc < min_soc:
                soc_crit = min_soc - current_soc
                h_crit = min(hours_needed, math.ceil((soc_crit / 100.0) * capacity / charge_speed))
                df_before = df_prices[df_prices['time_start_dt'] < deadline]
                if not df_before.empty:
                    df_crit = df_before.sort_values('price_sek')
                    cheapest_hours.extend(df_crit.head(h_crit)['time_start'].tolist())
            
            remaining_h = hours_needed - len(cheapest_hours)
            if remaining_h > 0:
                df_opp = df_prices[~df_prices['time_start'].isin(cheapest_hours)].sort_values('price_sek')
                cheapest_hours.extend(df_opp.head(remaining_h)['time_start'].tolist())

        charging_plan = [1 if p['time_start'] in cheapest_hours else 0 for p in prices_with_forecast]
        
        analysis = [
            f"Mål: <b>{target_soc}%</b> ({mode})",
            f"Behov: <b>{hours_needed} timmar</b> laddning.",
            f"Status: Mercedes SoC är {current_soc}%."
        ]
        
        if not merc_state.get('plugged_in', False):
            analysis.append("<i class='bi bi-info-circle text-info'></i> <i>Visar hypotetisk plan (ej inkopplad).</i>")
        
        if hours_needed > 0 and cheapest_hours:
            start_times = [pd.to_datetime(t) for t in cheapest_hours]
            next_start = min(start_times).strftime("%H:%M")
            analysis.append(f"Optimal starttid: <b>{next_start}</b>")
        
        return jsonify({
            "prices": prices_with_forecast,
            "plan": charging_plan,
            "weather": weather_forecast,
            "analysis": analysis
        })
    except Exception as e:
        app.logger.error(f"Error in api_plan: {e}", exc_info=True)
        return jsonify({"error": str(e), "prices": [], "plan": []}), 500

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'POST':
        data = request.json
        current = ConfigManager.get_settings()
        current.update(data)
        if ConfigManager.save_settings(current):
            trigger_path = STATE_PATH.parent / "trigger_update"
            try: trigger_path.touch()
            except: pass
            return jsonify({"status": "ok"})
        return jsonify({"status": "error"}), 500
    return jsonify(ConfigManager.get_settings())

@app.route('/api/override', methods=['POST'])
def api_override():
    data = request.json
    vehicle_id = data.get('vehicle_id', 'mercedes_eqv')
    action = data.get('action')
    duration = data.get('duration', 60)
    set_override(vehicle_id, action, duration)
    trigger_path = STATE_PATH.parent / "trigger_update"
    try: trigger_path.touch()
    except: pass
    return jsonify({"status": "ok"})

@app.route('/api/control', methods=['POST'])
def api_control():
    try:
        data = request.json
        vehicle_id = data.get('vehicle_id')
        action = data.get('action')

        full_config = ConfigManager.load_full_config()
        if vehicle_id != 'mercedes_eqv':
            return jsonify({"status": "error", "message": "Vehicle not found"}), 404

        car_obj = MercedesEQV(full_config['cars']['mercedes_eqv'])

        if action == 'climate_start':
            success = car_obj.start_climate()
        elif action == 'climate_stop':
            success = car_obj.stop_climate()
        else:
            return jsonify({"status": "error", "message": "Unknown action"}), 400

        if success:
            return jsonify({"status": "ok", "message": f"Command {action} sent."})
        else:
            return jsonify({"status": "error", "message": "Command failed or not configured."}), 500
    except Exception as e:
        app.logger.error(f"Error in api_control: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
