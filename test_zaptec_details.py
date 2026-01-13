import json
import os
from src.connectors.zaptec import ZaptecCharger
from src.config_manager import ConfigManager

def diagnose():
    config = ConfigManager.load_full_config()
    zaptec_config = config['charger']['zaptec']
    charger = ZaptecCharger(zaptec_config)
    
    # We want to see the RAW data from Zaptec API
    target_id = charger.charger_id if charger.charger_id else charger.installation_id
    headers = charger._get_headers()
    if not headers:
        print("Auth failed")
        return

    url = f"{charger.api_url}/chargers/{target_id}/state"
    import requests
    response = requests.get(url, headers=headers)
    data = response.json()
    
    print(f"--- Zaptec Detailed State for {target_id} ---")
    relevant_ids = {
        510: "Total Power (W)",
        511: "L1 Power (W)",
        512: "L2 Power (W)",
        513: "L3 Power (W)",
        501: "L1 Current (A)",
        502: "L2 Current (A)",
        503: "L3 Current (A)",
        710: "Operating Mode",
        101: "Max Current Setting (A)"
    }
    
    for obs in data:
        state_id = obs.get('StateId')
        if state_id in relevant_ids:
            print(f"{relevant_ids[state_id]:<25}: {obs.get('ValueAsString')}")

if __name__ == "__main__":
    diagnose()
