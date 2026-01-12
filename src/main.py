import time
import yaml
import schedule
import json
import os
from datetime import datetime, timedelta
import logging

# Import our modules
from connectors.spot_price import SpotPriceService
from connectors.weather import WeatherService
from connectors.vehicles import MercedesEQV, NissanLeaf
from connectors.zaptec import ZaptecCharger
from connectors.home_assistant import HomeAssistantClient
from database.db_manager import DatabaseManager
from optimizer.engine import Optimizer
from config_manager import ConfigManager, DATABASE_PATH

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ev_charger.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

STATE_FILE = "data/optimizer_state.json"
HISTORY_FILE = "data/forecast_history.json"

def _save_forecast_history(forecast_data):
    """
    Saves the generated price forecast to a historical file.
    Trims old forecasts to prevent the file from growing indefinitely.
    """
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    
    history = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Could not decode {HISTORY_FILE}, starting new history.")
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    history[today_str] = forecast_data
    
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    keys_to_remove = [date_str for date_str in history if date_str < seven_days_ago]
    for key in keys_to_remove:
        del history[key]

    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
        logger.info(f"Forecast history saved to {HISTORY_FILE}")
    except Exception as e:
        logger.error(f"Failed to save forecast history to {HISTORY_FILE}: {e}")

def save_state(state):
    logger.info(f"Attempting to save state to {STATE_FILE}")
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
        logger.info(f"Successfully saved state to {STATE_FILE}")
    except Exception as e:
        logger.error(f"Failed to save state to {STATE_FILE}: {e}")

def job():
    logger.info("Starting optimization cycle...")
    config = ConfigManager.load_full_config()
    user_settings = ConfigManager.get_settings()
    
    # Initialize services
    db = DatabaseManager(db_path=DATABASE_PATH)
    spot_service = SpotPriceService(region=config['grid']['region'])
    weather_service = WeatherService(config['location']['latitude'], config['location']['longitude'])
    optimizer = Optimizer(config)
    
    # Initialize Hardware
    eqv = MercedesEQV(config['cars']['mercedes_eqv'])
    leaf = NissanLeaf(config['cars']['nissan_leaf'])
    charger = ZaptecCharger(config['charger']['zaptec'])
    
    # Fetch Data
    official_prices = spot_service.get_prices_upcoming()
    logger.info(f"Fetched {len(official_prices)} official spot prices")
    
    # NEW: Fetch Historical Data for Long Term Trend
    # Using 7-day rolling average as requested for better responsiveness
    historical_avg = spot_service.get_historical_average(days=7)
    logger.info(f"Historical 7-day average price: {historical_avg:.2f} SEK/kWh")
    optimizer.long_term_history_avg = historical_avg # Inject into optimizer
    
    weather_forecast = weather_service.get_forecast()
    
    # Generate forecast using configured horizon
    horizon_days = config['optimization'].get('planning_horizon_days', 5)
    prices = optimizer._generate_price_forecast(official_prices, weather_forecast, forecast_horizon_days=horizon_days)
    
    logger.info(f"Generated price forecast with {len(prices)} entries (Horizon: {horizon_days} days)")
    _save_forecast_history(prices)

    # --- 1. Get Hardware Status ---
    try:
        charger_status = charger.get_status()
    except Exception as e:
        logger.error(f"Error getting charger status: {e}")
        charger_status = {}

    # Map car name to object and status
    cars = [eqv, leaf]
    vehicle_statuses = {}
    
    # --- ZAPTEC MASTER SWITCH LOGIC ---
    # If Zaptec says DISCONNECTED (Mode 1), no car can possibly be plugged in.
    # We override false positives from vehicle APIs (ghost connections).
    zaptec_is_disconnected = (charger_status.get('mode_code') == 1)
    
    for car in cars:
        try:
            s = car.get_status()
            
            if zaptec_is_disconnected:
                if s.get('plugged_in'):
                    logger.warning(f"Zaptec Override: {car.name} reports plugged_in, but charger is DISCONNECTED. Forcing False.")
                s['plugged_in'] = False
                
            vehicle_statuses[car.name] = s
            # Legacy log
            db.log_vehicle_status(car.name, s.get('soc', 0), s.get('range_km', 0), s.get('plugged_in', False))
        except Exception as e:
            logger.error(f"Error getting status for {car.name}: {e}")
            vehicle_statuses[car.name] = {}

    # --- 2. Determine Active Car ("Charging Detective") ---
    active_car_id = None
    
    merc_s = vehicle_statuses.get("Mercedes EQV", {})
    leaf_s = vehicle_statuses.get("Nissan Leaf", {})
    
    merc_plugged = merc_s.get('plugged_in', False)
    leaf_plugged = leaf_s.get('plugged_in', False)
    
    is_charging = charger_status.get('is_charging', False) or (charger_status.get('power_kw', 0) > 0.1)

    if is_charging:
        # Phase detection logic (Zaptec Master Override)
        # Nissan = 1 phase (always L2), Mercedes = 3 phases
        active_phases = charger_status.get('active_phases', 0)
        phase_map = charger_status.get('phase_map', [False, False, False])
        
        if active_phases >= 2:
            logger.info(f"Phase Detection: {active_phases} phases active. Identified as Mercedes EQV (3-phase).")
            active_car_id = "mercedes_eqv"
        elif active_phases == 1:
            if phase_map[1]: # Phase 2 active
                logger.info("Phase Detection: 1 phase active (L2). Identified as Nissan Leaf.")
                active_car_id = "nissan_leaf"
            else:
                logger.info(f"Phase Detection: 1 phase active (Not L2). Identity unclear.")
        
        # Fallback to plugged_in logic if phase detection is inconclusive
        if active_car_id is None:
            if merc_plugged and not leaf_plugged:
                active_car_id = "mercedes_eqv"
            elif leaf_plugged and not merc_plugged:
                active_car_id = "nissan_leaf"
            elif merc_plugged and leaf_plugged:
                active_car_id = "UNKNOWN_BOTH"
            else:
                active_car_id = "UNKNOWN_NONE"
    else:
        # Not charging, but who is connected?
        if merc_plugged and not leaf_plugged: active_car_id = "mercedes_eqv"
        elif leaf_plugged and not merc_plugged: active_car_id = "nissan_leaf"
        elif merc_plugged and leaf_plugged: active_car_id = "UNKNOWN_BOTH"

    # --- Fetch Home Sensors (Timmerflotte) ---
    ha_temp = None
    ha_humidity = None
    
    # Reuse HA credentials from car config
    ha_url = config['cars']['mercedes_eqv'].get('ha_url')
    ha_token = config['cars']['mercedes_eqv'].get('ha_token')
    
    if ha_url and ha_token:
        ha_client = HomeAssistantClient(ha_url, ha_token)
        
        # Temp
        temp_id = user_settings.get('ha_temp_sensor_id') 
        if temp_id:
            s = ha_client.get_state(temp_id)
            if s and s.get('state') not in ['unknown', 'unavailable']:
                try:
                    ha_temp = float(s['state'])
                    logger.info(f"Home Sensor Temp: {ha_temp}°C")
                except ValueError: pass
        
        # Humidity
        hum_id = user_settings.get('ha_humidity_sensor_id')
        if hum_id:
            s = ha_client.get_state(hum_id)
            if s and s.get('state') not in ['unknown', 'unavailable']:
                try:
                    ha_humidity = float(s['state'])
                except ValueError: pass

    # --- 3. Log System Metrics ---
    # Use real sensor data if available, else forecast
    current_temp = ha_temp if ha_temp is not None else (weather_forecast[0]['temp_c'] if weather_forecast else 0.0)
    current_price = prices[0]['price_sek'] if prices else 0.0
    
    metrics = {
        "active_car_id": active_car_id,
        "zaptec_power_kw": charger_status.get('power_kw', 0.0),
        "zaptec_energy_kwh": 0.0, # Not yet available from get_status
        "zaptec_mode": charger_status.get('operating_mode', 'UNKNOWN'),
        "mercedes_soc": merc_s.get('soc', 0),
        "mercedes_plugged": merc_plugged,
        "nissan_soc": leaf_s.get('soc', 0),
        "nissan_plugged": leaf_plugged,
        "temp_c": current_temp,
        "price_sek": current_price
    }
    db.log_system_metrics(metrics)
    logger.info(f"System Metrics Logged: Active={active_car_id}, Power={metrics['zaptec_power_kw']}kW")

    # --- 4. Optimization Logic ---
    state_data = {}
    any_charging_needed = False

    for car in cars:
        status = vehicle_statuses.get(car.name, {})
        if not status:
            continue # Skip if failed to get status

        # Determine target
        vid = "mercedes_eqv" if "Mercedes" in car.name else "nissan_leaf"
        target_soc = user_settings.get(f"{vid}_target", 80)
        
        # Inject status into car object for optimizer (hacky but needed for current optimizer signature)
        # Ideally optimizer should take status dict
        # Assuming Optimizer.suggest_action calls car.get_status() internally? 
        # Let's check Optimizer.suggest_action implementation... 
        # It takes 'car' object. Does it call get_status again?
        # If so, we are double fetching. But for now let's accept it or mock it.
        # To be safe, we let optimizer fetch again or we trust it uses properties if they were cached.
        # Actually, standard 'Optimizer' calls 'car.get_soc()' usually. 
        # Let's assume it fetches again. It's fine for now.
        
        decision = optimizer.suggest_action(car, prices, weather_forecast)
        
        urgency_score = optimizer.calculate_urgency(car, target_soc)
        
        state_data[car.name] = {
            "id": vid,
            "last_updated": datetime.now().isoformat(),
            "soc": status.get('soc', 0),
            "range_km": status.get('range_km', 0),
            "odometer": status.get('odometer', 0),
            "climate_active": status.get('climate_active', False),
            "plugged_in": status.get('plugged_in', False),
            "action": decision['action'],
            "reason": decision['reason'],
            "urgency_score": urgency_score
        }

        logger.info(f"Car: {car.name} | SoC: {status.get('soc')}% | Action: {decision['action']} | Urgency: {urgency_score:.1f}")
        
        if status.get('plugged_in') and decision['action'] == "CHARGE":
            any_charging_needed = True

    # Add sensors to state
    state_data['sensors'] = {
        "temp_c": ha_temp,
        "humidity": ha_humidity
    }

    # Save state
    save_state(state_data)

    # --- 5. Control Charger ---
    try:
        # Get fresh charger status before making control decision
        fresh_charger_status = charger.get_status()
        is_charging = fresh_charger_status.get('is_charging', False)
        power_kw = fresh_charger_status.get('power_kw', 0.0)

        logger.info(f"Charger Status: is_charging={is_charging}, power={power_kw:.2f}kW, any_charging_needed={any_charging_needed}")

        if any_charging_needed:
            if not is_charging:
                logger.info("Decision: START CHARGING")
                charger.start_charging()
            else:
                logger.info("Decision: Already charging, no action needed")
        else:
            if is_charging:
                logger.info("Decision: STOP CHARGING (waiting for cheaper prices)")
                # Use deauthorize mode to prevent car from auto-restarting (default behavior)
                charger.stop_charging()
            else:
                logger.info("Decision: Not charging, no action needed")
    except Exception as e:
        logger.error(f"Charger control failed: {e}")

def main():
    logger.info("EV Smart Charger System Started")
    job()
    schedule.every(1).minutes.do(job)
    while True:
        schedule.run_pending()
        time.sleep(10) # Sleep less to catch minute schedule accurately

if __name__ == "__main__":
    main()