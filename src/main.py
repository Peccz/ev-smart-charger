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

# Module-level service instances — reused across cycles to preserve in-memory caches
_charger = None
_spot_service = None
_weather_service = None

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
    global _charger, _spot_service, _weather_service
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
    if _spot_service is None:
        _spot_service = SpotPriceService(region=config['grid']['region'])
    if _weather_service is None:
        _weather_service = WeatherService(config['location']['latitude'], config['location']['longitude'])
    spot_service = _spot_service
    weather_service = _weather_service
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
    if _charger is None:
        _charger = ZaptecCharger(config['charger']['zaptec'])
    charger = _charger
    
    # Fetch Data
    official_prices = spot_service.get_prices_upcoming()
    historical_avg = spot_service.get_historical_average(days=7)
    optimizer.long_term_history_avg = historical_avg
    weather_forecast = weather_service.get_forecast()
    
    horizon_days = config['optimization'].get('planning_horizon_days', 5)
    prices = optimizer._generate_price_forecast(official_prices, weather_forecast, forecast_horizon_days=horizon_days)
    _save_forecast_history(prices)

    # --- 2. Status Updates ---
    api_error_count = state_data.get('api_error_count', 0)
    try:
        charger_status = charger.get_status()
        api_error_count = 0
    except Exception:
        charger_status = {}
        api_error_count += 1
        logger.warning(f"Zaptec API unavailable (error #{api_error_count})")

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
    
    merc_plugged = merc_s.get('plugged_in', False)
    if is_charging:
        active_phases = charger_status.get('active_phases', 0)
        # Mercedes is 3-phase. Use plugged_in as primary signal to avoid misidentifying
        # a 3-phase guest charger as Mercedes when Mercedes is home but not connected.
        if merc_plugged and (active_phases >= 2 or active_phases == 0):
            active_car_id = "mercedes_eqv"
        elif merc_plugged and active_phases == 1:
            active_car_id = "mercedes_eqv"  # 1-phase home socket fallback
        else:
            active_car_id = "UNKNOWN_GUEST"
    elif zaptec_mode in [2, 3, 5]:
        active_car_id = "mercedes_eqv" if merc_plugged else "UNKNOWN_GUEST"
    else:
        active_car_id = "UNKNOWN_NONE"

    # --- 4. Logic & State ---
    current_session_id = state_data.get('session_id')
    prev_session_energy = state_data.get('prev_session_energy', 0.0)
    last_prune_date = state_data.get('last_prune_date', '')
    last_guard_notification = state_data.get('last_guard_notification', '')
    climate_triggered_date = state_data.get('climate_triggered_date', '')
    state_data = {
        'session_id': current_session_id,
        'session_assigned_id': state_data.get('session_assigned_id'),
        'charger_guard': guard.state,
        'api_error_count': api_error_count,
        'last_prune_date': last_prune_date,
        'last_guard_notification': last_guard_notification,
        'climate_triggered_date': climate_triggered_date,
    }

    # Daily DB pruning
    today_str = datetime.now().strftime("%Y-%m-%d")
    if last_prune_date != today_str:
        db.prune_old_data(days=30)
        state_data['last_prune_date'] = today_str
        logger.info("DB: Pruned rows older than 30 days.")
    
    any_charging_needed = False
    decision = optimizer.suggest_action(eqv, prices, weather_forecast)
    dynamic_target, optimization_mode = optimizer._calculate_dynamic_target("mercedes_eqv", prices)

    state_data["Mercedes EQV"] = {
        "id": "mercedes_eqv",
        "last_updated": datetime.now().isoformat(),
        "soc": merc_s.get('soc', 0),
        "plugged_in": merc_s.get('plugged_in', False),
        "action": decision['action'],
        "reason": decision['reason'],
        "urgency_score": optimizer.calculate_urgency(eqv, dynamic_target)
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
        elif desired_action == "STOP":
            if is_charging:
                charger.stop_charging()
            # Always register STOP to clear any lingering START state in the guard
            guard.register_command("STOP")
        state_data['last_guard_notification'] = ''  # Reset when guard is OK
    else:
        state_data["guard_msg"] = msg
        # Send HA notification on new guard block (not every minute)
        if msg != last_guard_notification:
            try:
                ha_cfg = config['cars']['mercedes_eqv']
                ha_notify = HomeAssistantClient(ha_cfg['ha_url'], ha_cfg['ha_token'])
                ha_notify.send_notification("EV Charger Varning", f"ChargerGuard: {msg}", "ev_charger_guard")
            except Exception as e:
                logger.warning(f"Failed to send HA notification: {e}")
            state_data['last_guard_notification'] = msg

    # --- 5.5. Pre-climate ---
    if merc_s.get('plugged_in') and merc_s.get('is_home', True) and not merc_s.get('climate_active', False):
        dep_str = user_settings.get('departure_time', '07:00')
        try:
            dep_h, dep_m = map(int, dep_str.split(':'))
            now_dt = datetime.now()
            dep_dt = now_dt.replace(hour=dep_h, minute=dep_m, second=0, microsecond=0)
            if dep_dt <= now_dt:
                dep_dt += timedelta(days=1)
            mins_to_dep = (dep_dt - now_dt).total_seconds() / 60
            if 20 <= mins_to_dep <= 35 and climate_triggered_date != today_str:
                if eqv.start_climate():
                    state_data['climate_triggered_date'] = today_str
                    logger.info(f"Pre-climate triggered: departure in {mins_to_dep:.0f} min")
        except Exception as e:
            logger.warning(f"Pre-climate error: {e}")

    # --- 6. Sessions ---
    if is_charging and active_car_id == "mercedes_eqv":
        power_kw = charger_status.get('power_kw', 0.0)
        current_energy_kwh = charger_status.get('energy_kwh', 0.0)
        current_price = prices[0]['price_sek'] if prices else 0.0

        if not current_session_id:
            current_session_id = db.start_session("mercedes_eqv", merc_s.get('soc', 0), merc_s.get('odometer', 0))
            state_data['session_assigned_id'] = "mercedes_eqv"
            prev_session_energy = current_energy_kwh
            energy_delta = 0.0
        else:
            # Use Zaptec session energy (kWh) for accurate delta; fall back to power snapshot
            if current_energy_kwh > 0:
                energy_delta = max(0.0, current_energy_kwh - prev_session_energy)
            else:
                energy_delta = power_kw / 60.0
            prev_session_energy = current_energy_kwh
            cost_grid = energy_delta * (grid_fee + energy_tax + retail_fee) * (1 + vat_rate)
            cost_spot = energy_delta * current_price
            db.update_session(current_session_id, energy_delta, cost_spot, cost_grid, merc_s.get('soc', 0), merc_s.get('odometer', 0))

        state_data['session_id'] = current_session_id
        state_data['prev_session_energy'] = prev_session_energy
    elif not is_charging and current_session_id:
        # Grace period: only close session if Zaptec has been reachable (not an API blip)
        if api_error_count < 3:
            db.end_session(current_session_id, merc_s.get('soc', 0), merc_s.get('odometer', 0))
            state_data['session_id'] = None
            state_data['session_assigned_id'] = None
            state_data['prev_session_energy'] = 0.0
        else:
            logger.warning(f"Zaptec API error count {api_error_count} — keeping session open during outage.")
            state_data['session_id'] = current_session_id

    save_state(state_data)

    # --- 7. Log optimizer cycle ---
    weather_now = weather_forecast[0] if weather_forecast else {}
    reference_price = None
    if prices:
        long_term_avg = getattr(optimizer, 'long_term_history_avg', None)
        reference_price = long_term_avg if long_term_avg else (sum(p['price_sek'] for p in prices) / len(prices))

    db.log_optimizer_cycle({
        'soc': merc_s.get('soc'),
        'plugged_in': merc_s.get('plugged_in', False),
        'is_charging': is_charging,
        'power_kw': charger_status.get('power_kw', 0.0),
        'zaptec_mode': zaptec_mode,
        'active_car_id': active_car_id,
        'session_id': state_data.get('session_id'),
        'action': decision['action'],
        'reason': decision['reason'],
        'optimization_mode': optimization_mode,
        'target_soc': dynamic_target,
        'current_price_sek': prices[0]['price_sek'] if prices else None,
        'reference_price_sek': reference_price,
        'hours_to_deadline': decision.get('hours_until_deadline'),
        'temp_c': weather_now.get('temp_c'),
        'wind_kmh': weather_now.get('wind_kmh_80m'),
        'solar_w_m2': weather_now.get('solar_w_m2'),
        'api_error_count': api_error_count,
        'guard_status': msg if not can_exec else 'OK',
    })

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
