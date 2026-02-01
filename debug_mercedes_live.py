import sys
import os
import json
import requests
import logging
from datetime import datetime

# Ensure src is in path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
from config_manager import ConfigManager

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("DebugMerc")

def main():
    config = ConfigManager.load_full_config()
    merc = config.get('cars', {}).get('mercedes_eqv', {})
    ha_url = merc.get('ha_url').rstrip('/')
    ha_token = merc.get('ha_token')
    
    if not ha_url or not ha_token:
        print("Error: No HA credentials found.")
        return

    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    
    print(f"Connecting to HA at {ha_url}...")
    
    # 1. Check current configured sensor
    current_id = merc.get('ha_merc_soc_entity_id', 'sensor.urg48t_state_of_charge')
    print(f"\n--- Checking Configured Sensor: {current_id} ---")
    try:
        resp = requests.get(f"{ha_url}/api/states/{current_id}", headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            state = data.get('state')
            last_updated = data.get('last_updated')
            attrs = data.get('attributes', {})
            print(f"State: {state}%")
            print(f"Last Updated: {last_updated}")
            print(f"Attributes: {json.dumps(attrs, indent=2)}")
        else:
            print(f"Error: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Exception: {e}")

    # 2. Search for ANY battery sensor
    print("\n--- Searching for ALL battery sensors ---")
    try:
        resp = requests.get(f"{ha_url}/api/states", headers=headers, timeout=15)
        all_states = resp.json()
        
        for s in all_states:
            eid = s.get('entity_id', '')
            val = s.get('state', '')
            
            # Filter for Mercedes/URG related battery stuff
            if ('urg48t' in eid or 'mercedes' in eid) and ('battery' in eid or 'soc' in eid or 'charge' in eid):
                 print(f"Found: {eid} = {val} (Last Upd: {s.get('last_updated')})")
            
    except Exception as e:
        print(f"Scan failed: {e}")

if __name__ == "__main__":
    main()
