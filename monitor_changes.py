import requests
import json
import os
import time
from datetime import datetime

SETTINGS_PATH = "data/user_settings.json"
LOG_FILE = "change_log.txt"

def get_settings():
    if not os.path.exists(SETTINGS_PATH):
        return None
    with open(SETTINGS_PATH, 'r') as f:
        return json.load(f)

def get_ha_states(base_url, token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{base_url.rstrip('/')}/api/states"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching states: {e}")
        return []

def main():
    settings = get_settings()
    if not settings:
        print("Settings not found.")
        return

    base_url = settings.get("ha_url")
    token = settings.get("ha_token")
    
    if not base_url or not token:
        print("HA credentials missing.")
        return

    print(f"Starting monitor. Logging changes to {LOG_FILE}...")
    
    # Filter for interesting entities
    keywords = ["urg48t", "leaf", "zaptec"]
    
    last_states = {}

    # Initial fetch
    print("Fetching initial state...")
    states = get_ha_states(base_url, token)
    for entity in states:
        eid = entity['entity_id']
        if any(k in eid for k in keywords):
            last_states[eid] = entity

    with open(LOG_FILE, "a") as f:
        f.write(f"--- Monitoring started at {datetime.now()} ---\n")

    while True:
        time.sleep(5) # Check every 5 seconds
        current_states_list = get_ha_states(base_url, token)
        
        changes_found = False
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        current_states_map = {}
        
        for entity in current_states_list:
            eid = entity['entity_id']
            if not any(k in eid for k in keywords):
                continue
            
            current_states_map[eid] = entity
            
            # Check for changes
            if eid in last_states:
                old = last_states[eid]
                
                # Compare state
                if old['state'] != entity['state']:
                    msg = f"[{timestamp}] {eid}: STATE changed '{old['state']}' -> '{entity['state']}'"
                    print(msg, flush=True)
                    with open(LOG_FILE, "a") as f: f.write(msg + "\n")
                    changes_found = True
                
                # Compare attributes (simplified)
                # Checking specific interesting attributes
                interesting_attrs = ['charging', 'pluggedIn', 'chargingstatus', 'chargingactive']
                for attr in interesting_attrs:
                    old_val = old.get('attributes', {}).get(attr)
                    new_val = entity.get('attributes', {}).get(attr)
                    if old_val != new_val:
                        msg = f"[{timestamp}] {eid}: ATTR '{attr}' changed '{old_val}' -> '{new_val}'"
                        print(msg, flush=True)
                        with open(LOG_FILE, "a") as f: f.write(msg + "\n")
                        changes_found = True

            else:
                msg = f"[{timestamp}] New entity found: {eid} = {entity['state']}"
                print(msg, flush=True)
                with open(LOG_FILE, "a") as f: f.write(msg + "\n")
        
        # Update last states
        last_states = current_states_map

if __name__ == "__main__":
    main()
