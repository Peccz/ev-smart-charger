import logging
import sys
import os
import json
import requests

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure src is in path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from config_manager import ConfigManager
from connectors.vehicles import HomeAssistantClient

def diagnose():
    logger.info("--- DIAGNOSING ODOMETER CONFIGURATION ---")
    
    # 1. Check ConfigManager Output
    config = ConfigManager.load_full_config()
    merc_config = config.get('cars', {}).get('mercedes_eqv', {})
    nissan_config = config.get('cars', {}).get('nissan_leaf', {})
    
    odo_merc_id = merc_config.get('odometer_entity_id')
    odo_nissan_id = nissan_config.get('odometer_entity_id')
    
    logger.info(f"1. ConfigManager 'mercedes_eqv' odometer_entity_id: '{odo_merc_id}'")
    logger.info(f"1. ConfigManager 'nissan_leaf' odometer_entity_id: '{odo_nissan_id}'")
    
    if not odo_merc_id:
        logger.error("CRITICAL: Mercedes odometer ID is MISSING in ConfigManager output!")
    else:
        logger.info("OK: Mercedes odometer ID found in config.")

    if not odo_nissan_id:
        logger.error("CRITICAL: Nissan odometer ID is MISSING in ConfigManager output!")
    else:
        logger.info("OK: Nissan odometer ID found in config.")

    # 2. Check HA Connection for these IDs
    ha_url = merc_config.get('ha_url')
    ha_token = merc_config.get('ha_token')
    
    if not ha_url or not ha_token:
        logger.error("CRITICAL: HA Credentials missing.")
        return

    client = HomeAssistantClient(ha_url, ha_token)
    
    for name, eid in [("Mercedes", odo_merc_id), ("Nissan", odo_nissan_id)]:
        if not eid:
            continue
            
        logger.info(f"\n--- Testing HA Fetch for {name} ({eid}) ---")
        state = client.get_state(eid)
        
        if state:
            logger.info(f"Raw HA Response: {json.dumps(state)}")
            val = state.get('state')
            logger.info(f"State Value: '{val}'")
            
            try:
                val_int = int(float(val))
                logger.info(f"Parsed Integer: {val_int} (SUCCESS)")
            except ValueError:
                logger.error(f"FAILED to parse '{val}' as integer.")
        else:
            logger.error(f"FAILED to get state from HA for {eid}. Check entity ID exists.")

if __name__ == "__main__":
    diagnose()
