import sys
import os
import json
import logging
import requests
import yaml

# Adjust path to import local modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from config_manager import ConfigManager
from connectors.vehicles import HomeAssistantClient

# Setup basic logging for the script
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def diagnose_ha_entities():
    logger.info("--- Home Assistant Entity Diagnoser ---")

    # 1. Load config
    config = ConfigManager.load_full_config()
    
    ha_url = None
    ha_token = None

    # Try to get HA config from Nissan Leaf or Mercedes EQV config
    if config.get('cars', {}).get('nissan_leaf', {}).get('ha_url'):
        ha_url = config['cars']['nissan_leaf']['ha_url']
        ha_token = config['cars']['nissan_leaf']['ha_token']
    elif config.get('cars', {}).get('mercedes_eqv', {}).get('ha_url'):
        ha_url = config['cars']['mercedes_eqv']['ha_url']
        ha_token = config['cars']['mercedes_eqv']['ha_token']

    if not ha_url or not ha_token:
        logger.error("Home Assistant URL or Token not found in car configurations (nissan_leaf or mercedes_eqv).")
        logger.error("Please ensure 'ha_url' and 'ha_token' are set in your config/settings.yaml.")
        return

    ha_client = HomeAssistantClient(ha_url, ha_token)
    logger.info(f"Connected to HA at: {ha_client.base_url}")

    # 2. Fetch all states
    try:
        # Direct call to get all states, as HomeAssistantClient.get_state expects an entity_id
        url = f"{ha_client.base_url}/api/states"
        response = requests.get(url, headers=ha_client.headers, timeout=20)
        response.raise_for_status()
        all_states = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching all HA states: {e}")
        return

    logger.info(f"Fetched {len(all_states)} entities from Home Assistant.")
    logger.info("\n--- Filtering for 'leaf' or 'nissan' related entities ---")

    filtered_entities = []
    for entity in all_states:
        entity_id = entity.get('entity_id', '')
        if 'leaf' in entity_id.lower() or 'nissan' in entity_id.lower():
            filtered_entities.append(entity)
            
    if not filtered_entities:
        logger.info("No entities found containing 'leaf' or 'nissan'. Displaying all entities.")
        filtered_entities = all_states # Display all if no specific ones found

    for entity in filtered_entities:
        entity_id = entity.get('entity_id')
        state = entity.get('state')
        attributes = entity.get('attributes', {})
        
        logger.info(f"\nEntity ID: {entity_id}")
        logger.info(f"  State: {state}")
        
        # Print only relevant attributes for brevity
        relevant_attrs = {}
        for k, v in attributes.items():
            if any(s in k.lower() for s in ['soc', 'range', 'battery', 'charge', 'plug', 'update', 'status', 'mode']):
                relevant_attrs[k] = v
        if relevant_attrs:
            logger.info(f"  Attributes (relevant): {json.dumps(relevant_attrs, indent=2)}")

    logger.info("\n--- Diagnosis Complete ---")
    logger.info("Look for entities related to 'State of Charge' (SoC), 'Battery Level', 'Range', 'Plugged In' status.")
    logger.info("These usually have entity_ids like 'sensor.nissan_leaf_battery_level' or 'binary_sensor.nissan_leaf_plugged_in'.")
    logger.info("Update your config/settings.yaml with the correct entity IDs.")


if __name__ == "__main__":
    diagnose_ha_entities()
