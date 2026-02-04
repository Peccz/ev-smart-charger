import sys
import os
import requests
import json
from datetime import datetime

# Ensure src is in path
sys.path.append(os.path.join(os.getcwd(), 'src'))
from config_manager import ConfigManager
from connectors.zaptec import ZaptecCharger

def dump_detailed_zaptec():
    print(f"--- ZAPTEC DEEP DIVE ({datetime.now()}) ---")
    config = ConfigManager.load_full_config()
    zap_cfg = config['charger']['zaptec']
    charger = ZaptecCharger(zap_cfg)
    
    headers = charger._get_headers()
    target_id = charger.charger_id or charger.installation_id
    
    # 1. Fetch State (Live Status)
    url_state = f"{charger.api_url}/chargers/{target_id}/state"
    print(f"Target ID: {target_id}")
    
    res = requests.get(url_state, headers=headers)
    if res.status_code != 200:
        print(f"Failed to get state: {res.status_code}")
        return

    states = res.json()
    states.sort(key=lambda x: x.get('StateId', 0))
    
    print(f"\n{'ID':<5} | {'Timestamp':<20} | {'Value':<15} | {'Description'}")
    print("-" * 80)
    
    # Karta över kända Zaptec State IDs
    known_map = {
        501: "Voltage L1 (V)",
        502: "Voltage L2 (V)",
        503: "Voltage L3 (V)",
        506: "Observational Mode (Read-only?)", 
        507: "Session Energy (kWh)",
        510: "Total Active Power (W)",
        511: "Power L1 (W)",
        512: "Power L2 (W)",
        513: "Power L3 (W)",
        710: "Operation Mode (Status)", # 1=Disc, 2=Waiting, 3=Charging
        713: "Authentication Status",
        723: "Last Session Detail"
    }

    for s in states:
        sid = int(s.get('StateId'))
        val = s.get('ValueAsString', '')
        ts = s.get('Timestamp', '')[0:19] # Truncate iso timestamp
        desc = known_map.get(sid, "Unknown")
        
        print(f"{sid:<5} | {ts:<20} | {val:<15} | {desc}")

if __name__ == "__main__":
    dump_detailed_zaptec()
