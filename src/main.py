import time
import schedule
import json
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler

# Import our modules
from connectors.spot_price import SpotPriceService
from connectors.weather import WeatherService
from connectors.vehicles import MercedesEQV
from connectors.zaptec import ZaptecCharger
from connectors.home_assistant import HomeAssistantClient
from database.db_manager import DatabaseManager
from optimizer.engine import Optimizer
from optimizer.charger_guard import ChargerGuard
from config_manager import ConfigManager, DATABASE_PATH, STATE_PATH, FORECAST_HISTORY_FILE, PROJECT_ROOT

# Setup logging
log_handler = RotatingFileHandler(PROJECT_ROOT / "ev_charger.log", maxBytes=2*1024*1024, backupCount=5)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[log_handler, logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Constants
GUARD_STATE_PATH = STATE_PATH.parent / "charger_guard_state.json"

def _save_forecast_history(forecast_data):
    history = {}
    if FORECAST_HISTORY_FILE.exists():
        try:
            with open(FORECAST_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except Exception: pass
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    history[today_str] = forecast_data
    limit_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    history = {k: v for k, v in history.items() if k >= limit_date}

    try:
        with open(FORECAST_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception: pass

def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(STATE_PATH, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception: pass

def job():
    logger.info("Starting optimization cycle...")
    config = ConfigManager.load_full_config()
    user_settings = ConfigManager.get_settings()
    
    grid_fee = config.get('grid_fee_sek_per_kwh', 0.25)
    energy_tax = config.get('energy_tax_sek_per_kwh', 0.36)
    retail_fee = config.get('retailer_fee_sek_per_kwh', 0.05)
    vat_rate = config.get('vat_rate', 0.25)
    total_grid_fee_unit = (grid_fee + energy_tax + retail_fee) * (1 + vat_rate)
    
    state_data = {}
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, 'r') as f:
                state_data = json.load(f)
        except Exception: pass
    
    db = DatabaseManager(db_path=DATABASE_PATH)
    spot_service = SpotPriceService(region=config['grid']['region'])
    weather_service = WeatherService(config['location']['latitude'], config['location']['longitude'])
    optimizer = Optimizer(config)
    guard = ChargerGuard(GUARD_STATE_PATH)
    
    # --- 1. Initialize Mercedes EQV ---
    # Nissan Leaf is now completely removed from the system.
    car_cfg = config['cars'].get('mercedes_eqv')
    if not car_cfg or not car_cfg.get('enabled', True):
        logger.warning("Mercedes EQV is not enabled or configured!")
        return

    eqv = MercedesEQV(car_cfg)
    eqv.max_charge_kw = db.get_learned_charge_speed("mercedes_eqv", eqv.max_charge_kw)
    
    active_vehicles = [eqv]
    charger = ZaptecCharger(config['charger']['zaptec'])
    
    # Fetch Data
    official_prices = spot_service.get_prices_upcoming()
    historical_avg = spot_service.get_historical_average(days=7)
    optimizer.long_term_history_avg = historical_avg
    weather_forecast = weather_service.get_forecast()
    
    horizon_days = config['optimization'].get('planning_horizon_days', 5)
    prices = optimizer._generate_price_forecast(official_prices, weather_forecast, forecast_horizon_days=horizon_days)
    _save_forecast_history(prices)

    # --- 2. Status Updates ---
    try:
        charger_status = charger.get_status()
    except Exception: charger_status = {}

    zaptec_mode = charger_status.get('mode_code', 0)
    zaptec_is_disconnected = (zaptec_mode == 1)
    is_charging = charger_status.get('is_charging', False) or (charger_status.get('power_kw', 0) > 0.1)
    
    vehicle_statuses = {}
    for car in active_vehicles:
        s = car.get_status()
        if zaptec_is_disconnected:
            s['plugged_in'] = False
        vehicle_statuses[car.name] = s
        db.log_vehicle_status(car.name, s.get('soc', 0), s.get('range_km', 0), s.get('plugged_in', False))

    # --- 3. Identification ---
    active_car_id = None
    merc_s = vehicle_statuses.get("Mercedes EQV", {})
    
    if is_charging:
        active_phases = charger_status.get('active_phases', 0)
        # Mercedes is 3-phase
        if active_phases >= 2 or merc_s.get('is_home'):
            active_car_id = "mercedes_eqv"
        else:
            active_car_id = "UNKNOWN_GUEST"
    elif zaptec_mode in [2, 3, 5]:
        active_car_id = "mercedes_eqv" if merc_s.get('plugged_in') else "UNKNOWN_GUEST"
    else:
        active_car_id = "UNKNOWN_NONE"

    # --- 4. Logic & State ---
    current_session_id = state_data.get('session_id')
    state_data = {
        'session_id': current_session_id,
        'session_assigned_id': state_data.get('session_assigned_id'),
        'charger_guard': guard.state
    }
    
    any_charging_needed = False
    target_soc = user_settings.get("mercedes_eqv_target", 80)
    decision = optimizer.suggest_action(eqv, prices, weather_forecast)
    
    state_data["Mercedes EQV"] = {
        "id": "mercedes_eqv",
        "last_updated": datetime.now().isoformat(),
        "soc": merc_s.get('soc', 0),
        "plugged_in": merc_s.get('plugged_in', False),
        "action": decision['action'],
        "reason": decision['reason'],
        "urgency_score": optimizer.calculate_urgency(eqv, target_soc)
    }

    if active_car_id == "mercedes_eqv" and decision['action'] == "CHARGE":
        any_charging_needed = True
    elif active_car_id == "UNKNOWN_GUEST":
        any_charging_needed = True # Always charge guests

    # --- 5. Control ---
    desired_action = "START" if any_charging_needed else "STOP"
    guard.validate_power(is_charging, charger_status.get('power_kw', 0.0))
    can_exec, msg = guard.can_execute(desired_action)
    
    if can_exec:
        if desired_action == "START" and not is_charging:
            if charger.start_charging():
                guard.register_command("START")
        elif desired_action == "STOP" and is_charging:
            if charger.stop_charging():
                guard.register_command("STOP")
    else:
        state_data["guard_msg"] = msg

    # --- 6. Sessions ---
    if is_charging and active_car_id == "mercedes_eqv":
        power_kw = charger_status.get('power_kw', 0.0)
        energy_delta = power_kw / 60.0
        cost_grid = energy_delta * (grid_fee + energy_tax + retail_fee) * (1 + vat_rate)
        current_price = prices[0]['price_sek'] if prices else 0.0
        cost_spot = energy_delta * current_price
        
        if not current_session_id:
            current_session_id = db.start_session("mercedes_eqv", merc_s.get('soc', 0), merc_s.get('odometer', 0))
            state_data['session_assigned_id'] = "mercedes_eqv"
        else:
            db.update_session(current_session_id, energy_delta, cost_spot, cost_grid, merc_s.get('soc', 0), merc_s.get('odometer', 0))
        state_data['session_id'] = current_session_id
    elif not is_charging and current_session_id:
        db.end_session(current_session_id, merc_s.get('soc', 0), merc_s.get('odometer', 0))
        state_data['session_id'] = None
        state_data['session_assigned_id'] = None

    save_state(state_data)

def main():
    logger.info("EV Smart Charger System Started (Mercedes EQV Only)")
    job()
    schedule.every(1).minutes.do(job)
    trigger_path = STATE_PATH.parent / "trigger_update"
    while True:
        if trigger_path.exists():
            try:
                trigger_path.unlink()
                job()
            except Exception: pass
        schedule.run_pending()
        time.sleep(5)

if __name__ == "__main__":
    main()
