import logging
import sys
import os
import json
import requests

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
from config_manager import ConfigManager

def find():
    config = ConfigManager.load_full_config()
    merc_config = config.get('cars', {}).get('mercedes_eqv', {})
    ha_url = merc_config.get('ha_url')
    ha_token = merc_config.get('ha_token')

    if not ha_url or not ha_token:
        logger.error("Inga HA-uppgifter.")
        return

    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    
    try:
        response = requests.get(f"{ha_url}/api/states", headers=headers, timeout=10)
        states = response.json()
        
        logger.info("--- SÖKER EFTER RELEVANTA SENSORER ---")
        
        for s in states:
            eid = s['entity_id'].lower()
            val = s['state']
            attrs = s.get('attributes', {})
            unit = str(attrs.get('unit_of_measurement', '')).lower()
            
            # Filter: Måste vara sensor
            if not eid.startswith('sensor'):
                continue

            is_merc = 'urg48t' in eid or 'mercedes' in eid
            is_leaf = 'leaf' in eid
            
            # Visa alla sensorer för bilarna som har "km" eller heter odometer
            if (is_merc or is_leaf) and ('odometer' in eid or 'km' in unit or 'distance' in eid):
                logger.info(f"ID: {eid}")
                logger.info(f"  State: {val}")
                logger.info(f"  Unit: {unit}")
                logger.info("-")

    except Exception as e:
        logger.error(e)

if __name__ == "__main__":
    find()
