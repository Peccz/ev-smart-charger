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

def inspect_specific_entities():
    config = ConfigManager.load_full_config()
    
    # Get HA credentials from config (which should be merged from secrets)
    merc_config = config.get('cars', {}).get('mercedes_eqv', {})
    ha_url = merc_config.get('ha_url')
    ha_token = merc_config.get('ha_token')

    if not ha_url or not ha_token:
        logger.error("HA Credentials not found in configuration.")
        return

    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }
    
    logger.info(f"Connecting to HA at {ha_url}...")

    # List of entities we are interested in
    target_entities = [
        "sensor.urg48t_state_of_charge",
        "sensor.urg48t_range_electric",
        "sensor.urg48t_odometer",
        "sensor.leaf_battery_level",
        "binary_sensor.leaf_plugged_in",
        "sensor.leaf_range_ac_on",
        "sensor.leaf_odometer"
    ]

    for entity_id in target_entities:
        try:
            url = f"{ha_url}/api/states/{entity_id}"
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                state = response.json()
                logger.info(f"--- {entity_id} ---")
                logger.info(f"State: {state.get('state')}")
                logger.info(f"Attributes: {json.dumps(state.get('attributes'), indent=2)}")
            else:
                logger.warning(f"--- {entity_id} ---")
                logger.warning(f"Status Code: {response.status_code}")
                logger.warning(f"Response: {response.text}")
                
        except Exception as e:
            logger.error(f"Failed to fetch {entity_id}: {e}")

if __name__ == "__main__":
    inspect_specific_entities()
