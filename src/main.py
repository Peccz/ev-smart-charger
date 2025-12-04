import time
import yaml
import schedule
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

def load_config():
    with open("config/settings.yaml", "r") as f:
        return yaml.safe_load(f)

def job():
    logger.info("Starting optimization cycle...")
    config = load_config()
    
    # Initialize services
    db = DatabaseManager()
    spot_service = SpotPriceService(region=config['grid']['region'])
    weather_service = WeatherService(config['location']['latitude'], config['location']['longitude'])
    optimizer = Optimizer(config)
    
    # Initialize Hardware
    # Note: In a real run, you would instantiate these once outside the loop if they hold connection state
    eqv = MercedesEQV(config['cars']['mercedes_eqv'])
    leaf = NissanLeaf(config['cars']['nissan_leaf'])
    charger = ZaptecCharger(config['charger']['zaptec'])
    
    # Fetch Data
    prices = spot_service.get_prices_upcoming()
    weather = weather_service.get_forecast()
    
    cars = [eqv, leaf]
    
    for car in cars:
        status = car.get_status()
        db.log_vehicle_status(car.name, status['soc'], status['range_km'], status['plugged_in'])
        
        decision = optimizer.suggest_action(car, prices, weather)
        logger.info(f"Car: {car.name} | SoC: {status['soc']}% | Action: {decision['action']} | Reason: {decision['reason']}")
        
        if status['plugged_in']:
            # Simple logic: If ANY plugged-in car needs charge, start charger.
            # Advanced logic would need Zaptec to support individual session management per RFID or phase.
            if decision['action'] == "CHARGE":
                charger.start_charging()
                # Assume we only charge one at a time or both get power
            else:
                charger.stop_charging()

def main():
    logger.info("EV Smart Charger System Started")
    
    # Run once on startup
    job()
    
    # Schedule hourly runs
    schedule.every().hour.at(":01").do(job)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
