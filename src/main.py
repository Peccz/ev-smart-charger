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
from database.db_manager import DatabaseManager
from optimizer.engine import Optimizer

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
    
    # Key by the start date of the forecast (e.g., "2025-12-05")
    today_str = datetime.now().strftime("%Y-%m-%d")
    history[today_str] = forecast_data
    
    # Trim old entries (e.g., keep last 7 days)
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

def load_config():
    with open("config/settings.yaml", "r") as f:
        base_config = yaml.safe_load(f)
    
    
    # Load user settings from JSON
    user_settings = {}
    try:
        with open("data/user_settings.json", "r") as f:
            user_settings = json.load(f)
    except FileNotFoundError:
        logger.info("user_settings.json not found, using defaults for user preferences.")
    except Exception as e:
        logger.error(f"Error loading user_settings.json: {e}")
        
    # --- MERGE CONFIGURATIONS ---
    # Create a new merged config for each car,
    # prioritizing user_settings for HA/API credentials and targets,
    # but keeping base_config for static car properties like capacity/max_charge.
    
    # Mercedes EQV Configuration
    merc_config_from_yaml = base_config['cars'].get('mercedes_eqv', {})
    mercedes_final_config = {
        'vin': merc_config_from_yaml.get('vin'),
        'capacity_kwh': merc_config_from_yaml.get('capacity_kwh', 90),
        'max_charge_kw': merc_config_from_yaml.get('max_charge_kw', 11),
        'target_soc': user_settings.get('mercedes_target', merc_config_from_yaml.get('target_soc', 80)),
        'ha_url': user_settings.get('ha_url'),
        'ha_token': user_settings.get('ha_token'),
        'ha_merc_soc_entity_id': user_settings.get('ha_merc_soc_entity_id')
    }
    base_config['cars']['mercedes_eqv'] = mercedes_final_config

    # Nissan Leaf Configuration
    nissan_config_from_yaml = base_config['cars'].get('nissan_leaf', {})
    nissan_final_config = {
        'vin': user_settings.get('nissan_vin', nissan_config_from_yaml.get('vin')),
        'capacity_kwh': nissan_config_from_yaml.get('capacity_kwh', 40),
        'max_charge_kw': nissan_config_from_yaml.get('max_charge_kw', 3.7),
        'target_soc': user_settings.get('nissan_target', nissan_config_from_yaml.get('target_soc', 80)),
        'username': user_settings.get('nissan_username', nissan_config_from_yaml.get('username')),
        'password': user_settings.get('nissan_password', nissan_config_from_yaml.get('password')),
        'region': nissan_config_from_yaml.get('region'),
        'ha_url': user_settings.get('ha_url'),
        'ha_token': user_settings.get('ha_token'),
        'ha_nissan_soc_entity_id': user_settings.get('ha_nissan_soc_entity_id'),
        'ha_nissan_plugged_entity_id': user_settings.get('ha_nissan_plugged_entity_id'),
        'ha_nissan_range_entity_id': user_settings.get('ha_nissan_range_entity_id')
    }
    base_config['cars']['nissan_leaf'] = nissan_final_config
            
    return base_config

def save_state(state):
    logger.info(f"Attempting to save state to {STATE_FILE}")
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
        logger.info(f"Successfully saved state to {STATE_FILE}")
    except Exception as e:
        logger.error(f"Failed to save state to {STATE_FILE}: {e}")

def get_user_settings():
    try:
        with open("data/user_settings.json", "r") as f:
            return json.load(f)
    except:
        return {}

def job():
    logger.info("Starting optimization cycle...")
    config = load_config()
    user_settings = get_user_settings() # Still needed for target_soc etc
    
    # Initialize services
    db = DatabaseManager()
    spot_service = SpotPriceService(region=config['grid']['region'])
    weather_service = WeatherService(config['location']['latitude'], config['location']['longitude'])
    optimizer = Optimizer(config)
    
    # Initialize Hardware
    # Pass merged config to car constructors
    eqv = MercedesEQV(config['cars']['mercedes_eqv'])
    leaf = NissanLeaf(config['cars']['nissan_leaf'])
    charger = ZaptecCharger(config['charger']['zaptec'])
    
    # Fetch Data
    official_prices = spot_service.get_prices_upcoming()
    weather_forecast = weather_service.get_forecast()
    
    # Generate full price forecast (official + estimated)
    prices = optimizer._generate_price_forecast(official_prices, weather_forecast)
    
    # Save this forecast for historical comparison (backtesting)
    _save_forecast_history(prices)

    cars = [eqv, leaf]
    state_data = {}
    any_charging_needed = False

    for car in cars:
        logger.info(f"Fetching status for {car.name}...")
        status = car.get_status()
        logger.info(f"{car.name} get_status() returned: {status}")
        db.log_vehicle_status(car.name, status['soc'], status['range_km'], status['plugged_in'])
        
        # Determine target
        vid = "mercedes_eqv" if "Mercedes" in car.name else "nissan_leaf"
        target_soc = user_settings.get(f"{vid}_target", 80)
        
        # Get recommendation
        decision = optimizer.suggest_action(car, prices, weather_forecast)
        
        # Calculate Urgency Score
        urgency_score = optimizer.calculate_urgency(car, target_soc)
        
        state_data[car.name] = {
            "id": vid,
            "last_updated": datetime.now().isoformat(),
            "soc": status['soc'],
            "range_km": status.get('range_km', 0),
            "odometer": status.get('odometer', 0),
            "plugged_in": status['plugged_in'],
            "action": decision['action'],
            "reason": decision['reason'],
            "urgency_score": urgency_score
        }

        logger.info(f"Car: {car.name} | SoC: {status['soc']}% | Action: {decision['action']} | Urgency: {urgency_score:.1f}")
        
        if status['plugged_in'] and decision['action'] == "CHARGE":
            any_charging_needed = True

    # Save state
    save_state(state_data)

    # Hardware Control
    try:
        charger_status = charger.get_status()
        if any_charging_needed:
            if not charger_status['is_charging']:
                charger.start_charging()
        else:
            if charger_status['is_charging']:
                charger.stop_charging()
    except Exception as e:
        logger.error(f"Charger control failed: {e}")

def main():
    logger.info("EV Smart Charger System Started")
    job()
    schedule.every().hour.at(":01").do(job)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
