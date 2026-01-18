import json
import os

SETTINGS_PATH = "data/user_settings.json"

def fix_settings():
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, 'r') as f:
            data = json.load(f)
        
        # Inject the correct sensor ID for Mercedes plugged status
        data['ha_merc_plugged_entity_id'] = "sensor.urg48t_charging_status"
        
        with open(SETTINGS_PATH, 'w') as f:
            json.dump(data, f, indent=2)
        print("Updated ha_merc_plugged_entity_id to sensor.urg48t_charging_status")
    else:
        print("Settings file not found")

if __name__ == "__main__":
    fix_settings()
