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
        
        print(f"Found {len(all_states)} entities. Filtering for Mercedes charging/connection indicators...")
        
        keywords = ["urg48t"]
        secondary_keywords = ["charg", "plug", "cable", "conn", "status", "range"]
        
        candidates = []
        for entity in all_states:
            entity_id = entity['entity_id'].lower()
            
            # Must contain 'urg48t'
            if not any(k in entity_id for k in keywords):
                continue
                
            # And ideally one of the secondary keywords
            if any(k in entity_id for k in secondary_keywords):
                candidates.append(entity)

        print(f"Found {len(candidates)} candidates:\n")
        
        for c in candidates:
            print(f"ID: {c['entity_id']}")
            print(f"State: {c['state']}")
            print(f"Attributes: {json.dumps(c.get('attributes', {}), indent=2, ensure_ascii=False)}")
            print("-" * 40)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
