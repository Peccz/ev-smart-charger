import requests
import json
import os

SETTINGS_PATH = "data/user_settings.json"

def get_settings():
    if not os.path.exists(SETTINGS_PATH):
        print("Error: user_settings.json not found.")
        return None
    with open(SETTINGS_PATH, 'r') as f:
        return json.load(f)

def main():
    settings = get_settings()
    if not settings:
        return

    base_url = settings.get("ha_url", "http://100.100.118.62:8123").rstrip('/')
    token = settings.get("ha_token")

    if not token:
        # Use hardcoded fallback for debug if needed, or rely on file
        print("Error: HA Token missing in settings.")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    url = f"{base_url}/api/states"
    print(f"Fetching all states from {url}...")
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        all_states = response.json()
        
        print(f"Found {len(all_states)} entities. Dumping ALL:")
        print("-" * 60)
        
        for c in all_states:
            eid = c['entity_id']
            # attributes = c.get('attributes', {})
            # if 'lat' in str(attributes) or 'lon' in str(attributes):
            if 'tracker' in eid or 'location' in eid:
                name = c.get('attributes', {}).get('friendly_name', 'No Name')
                print(f"{eid:<50} | {name} | {c['state']}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()