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
    zaptec_mode = charger_status.get('mode_code', 0)
    zaptec_connected = zaptec_mode in [2, 3, 5] # Connected, Charging, Done

    # Phase detection logic (Run when charging to confirm identity)
    if is_charging:
        # Phase detection logic (Zaptec Master Override)
        # Nissan = 1 phase (always L2), Mercedes = 3 phases
        active_phases = charger_status.get('active_phases', 0)
        phase_map = charger_status.get('phase_map', [False, False, False])
        
        hypothesis = "UNKNOWN_GUEST"
        if active_phases >= 2: 
            hypothesis = "mercedes_eqv"
        elif active_phases == 1 and phase_map[1]: 
            hypothesis = "nissan_leaf"
            
        # Verify hypothesis with API
        merc_charging = merc_s.get('is_charging', False)
        leaf_charging = leaf_s.get('is_charging', False)
        
        if hypothesis == "mercedes_eqv":
            if merc_charging:
                logger.info(f"Phase Detection (3-phase) confirmed by Mercedes API. Active car: Mercedes EQV")
                active_car_id = "mercedes_eqv"
            else:
                logger.info(f"Phase Detection suggests Mercedes, but API says not charging. Treating as GUEST/Waiting...")
                active_car_id = "UNKNOWN_GUEST"
        elif hypothesis == "nissan_leaf":
            if leaf_charging:
                logger.info(f"Phase Detection (L2) confirmed by Nissan API. Active car: Nissan Leaf")
                active_car_id = "nissan_leaf"
            else:
                logger.info(f"Phase Detection suggests Nissan, but API says not charging. Treating as GUEST/Waiting...")
                active_car_id = "UNKNOWN_GUEST"
        else:
            # Ambiguous phases. Check APIs directly.
            if merc_charging and not leaf_charging: active_car_id = "mercedes_eqv"
            elif leaf_charging and not merc_charging: active_car_id = "nissan_leaf"
            else: active_car_id = "UNKNOWN_GUEST"
        
        # Fallback to plugged_in logic if phase detection is inconclusive
    # Fallback / Discovery Logic (When not charging or identity unsure)
    if active_car_id is None:
        if zaptec_connected:
            # If Zaptec sees a car, we must decide who it is.
            if merc_plugged and not leaf_plugged:
                active_car_id = "mercedes_eqv"
            elif leaf_plugged and not merc_plugged:
                active_car_id = "nissan_leaf"
            else:
                # Ambiguous state (Both plugged or Neither plugged but Zaptec connected)
                # Treat as GUEST to force charging and trigger Phase Detection
                active_car_id = "UNKNOWN_GUEST"
                logger.info("Zaptec connected but car identity ambiguous. Treating as GUEST to force identification.")
        else:
            active_car_id = "UNKNOWN_NONE"

    # --- 3. Log System Metrics ---
    current_temp = weather_forecast[0]['temp_c'] if weather_forecast else 0.0
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
        
        # Only run optimizer if we identified this car as the active one
        # OR if we are not charging (just planning)
        # But if active_car_id is set to the OTHER car, we should force IDLE.
        
        # Logic: Always calculate plan, but only allow CHARGE if active_car_id matches (or is None/Guest)
        decision = optimizer.suggest_action(car, prices, weather_forecast)
        
        # Override decision if another car is definitely active
        if active_car_id and active_car_id not in ["UNKNOWN_GUEST", "UNKNOWN_NONE"]:
            if active_car_id != vid:
                decision = {"action": "IDLE", "reason": f"Other car ({active_car_id}) is active"}

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
        
        # If this car is the identified active car, respect its decision
        if active_car_id == vid and decision['action'] == "CHARGE":
            any_charging_needed = True

    # Guest / Identification Force Charge
    if active_car_id == "UNKNOWN_GUEST":
        logger.info("Unknown/Guest car connected. Force charging to identify.")
        any_charging_needed = True
        state_data["Guest"] = {
            "id": "guest",
            "name": "Identifierar...",
            "soc": 50,
            "plugged_in": True,
            "action": "CHARGE",
            "reason": "Analyserar faser..."
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