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

def find_entities():
    config = ConfigManager.load_full_config()
    
    # Get HA credentials (merged from secrets and settings)
    # Since we updated ConfigManager, it should have the correct priority.
    # But let's grab them from the mercedes config block as a proxy, since they are shared or global
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

    try:
        response = requests.get(f"{ha_url}/api/states", headers=headers, timeout=10)
        response.raise_for_status()
        states = response.json()
        
        logger.info(f"Found {len(states)} entities total.")
        logger.info("-" * 40)
        logger.info("Potential NISSAN LEAF control entities:")
        
        found = False
        for entity in states:
            eid = entity['entity_id'].lower()
            if 'leaf' in eid and ('button' in eid or 'switch' in eid or 'script' in eid or 'update' in eid or 'refresh' in eid):
                logger.info(f"  - {eid} (State: {entity['state']})")
                if 'attributes' in entity:
                    friendly_name = entity['attributes'].get('friendly_name', 'Unknown')
                    logger.info(f"    Friendly Name: {friendly_name}")
                found = True
        
        if not found:
            logger.info("  No obvious update/control entities found containing 'leaf'.")

        logger.info("-" * 40)
        logger.info("Potential MERCEDES control entities:")
        for entity in states:
            eid = entity['entity_id'].lower()
            if ('mercedes' in eid or 'urg48t' in eid or 'eqv' in eid) and ('button' in eid or 'switch' in eid or 'lock' in eid):
                logger.info(f"  - {eid}")

    except Exception as e:
        logger.error(f"Failed to fetch entities: {e}")

if __name__ == "__main__":
    find_entities()
