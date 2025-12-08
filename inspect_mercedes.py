import logging
import sys
import os
import json
import requests

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Ensure src is in path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from config_manager import ConfigManager

def inspect_entity(entity_id):
    config = ConfigManager.load_full_config()
    
    # Get HA credentials
    merc_config = config.get('cars', {}).get('mercedes_eqv', {})
    ha_url = merc_config.get('ha_url')
    ha_token = merc_config.get('ha_token')

    if not ha_url or not ha_token:
        logger.error("HA Credentials not found.")
        return

    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }
    
    url = f"{ha_url}/api/states/{entity_id}"
    logger.info(f"Fetching state for {entity_id}...")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        state = response.json()
        
        logger.info(json.dumps(state, indent=2))
        
        # Analyze Plugged Logic
        attrs = state.get('attributes', {})
        print("\n--- ANALYSIS ---")
        
        chargingactive = attrs.get('chargingactive')
        print(f"chargingactive: {chargingactive} (Type: {type(chargingactive)})")
        
        chargingstatus = attrs.get('chargingstatus')
        print(f"chargingstatus: {chargingstatus} (Type: {type(chargingstatus)})")
        
        is_plugged = False
        if chargingactive:
            print("-> Plugged because chargingactive is Truthy")
            is_plugged = True
        
        if chargingstatus is not None:
            val = str(chargingstatus).lower()
            if val not in ['3', 'disconnected', 'null', 'off', 'unavailable', 'unknown']:
                print(f"-> Plugged because chargingstatus '{val}' is NOT in exclude list")
                is_plugged = True
            else:
                print(f"-> NOT Plugged because chargingstatus '{val}' IS in exclude list")
        
        print(f"RESULT: Plugged In = {is_plugged}")

    except Exception as e:
        logger.error(f"Failed: {e}")

if __name__ == "__main__":
    inspect_entity("sensor.urg48t_range_electric")
