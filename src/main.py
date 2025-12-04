import time
import yaml
import schedule
import json
import os
from datetime import datetime
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

def load_config():
    with open("config/settings.yaml", "r") as f:
        return yaml.safe_load(f)

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

def get_user_settings():
    try:
        with open("data/user_settings.json", "r") as f:
            return json.load(f)
    except:
        return {}

def job():
    logger.info("Starting optimization cycle...")
    config = load_config()
    user_settings = get_user_settings()
    
    # Initialize services
    db = DatabaseManager()
    spot_service = SpotPriceService(region=config['grid']['region'])
    weather_service = WeatherService(config['location']['latitude'], config['location']['longitude'])
    optimizer = Optimizer(config)
    
    # Initialize Hardware
    eqv = MercedesEQV(config['cars']['mercedes_eqv'])
    leaf = NissanLeaf(config['cars']['nissan_leaf'])
    charger = ZaptecCharger(config['charger']['zaptec'])
    
    # Fetch Data
    prices = spot_service.get_prices_upcoming()
    weather = weather_service.get_forecast()
    
    cars = [eqv, leaf]
    state_data = {}
    any_charging_needed = False

    for car in cars:
        status = car.get_status()
        db.log_vehicle_status(car.name, status['soc'], status['range_km'], status['plugged_in'])
        
        # Determine target
        vid = "mercedes_eqv" if "Mercedes" in car.name else "nissan_leaf"
        target_soc = user_settings.get(f"{vid}_target", 80)
        
        # Get recommendation
        decision = optimizer.suggest_action(car, prices, weather)
        
        # Calculate Urgency Score
        urgency_score = optimizer.calculate_urgency(car, target_soc)
        
        state_data[car.name] = {
            "id": vid,
            "last_updated": datetime.now().isoformat(),
            "soc": status['soc'],
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
