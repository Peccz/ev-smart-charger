from src.connectors.zaptec import ZaptecCharger
from src.config_manager import ConfigManager
import requests

def find_install():
    config = ConfigManager.load_full_config()
    zaptec_config = config['charger']['zaptec']
    charger = ZaptecCharger(zaptec_config)
    
    headers = charger._get_headers()
    if not headers:
        print("Auth failed")
        return

    # Try to fetch charger details to see installation ID
    if charger.charger_id:
        url = f"{charger.api_url}/chargers/{charger.charger_id}"
        print(f"Fetching details for charger {charger.charger_id}...")
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            print(f"Installation ID: {data.get('InstallationId')}")
            print(f"Circuit ID: {data.get('CircuitId')}")
            print(f"Active: {data.get('Active')}")
        else:
            print(f"Failed to get charger details: {res.status_code}")

if __name__ == "__main__":
    find_install()
