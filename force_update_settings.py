import json
import os

SETTINGS_PATH = "data/user_settings.json"

def force_max():
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, 'r') as f:
            data = json.load(f)
        
        # Force Mercedes to 100/100 to trigger immediate charge
        data['mercedes_eqv_min_soc'] = 100
        data['mercedes_eqv_max_soc'] = 100
        data['mercedes_target'] = 100
        
        with open(SETTINGS_PATH, 'w') as f:
            json.dump(data, f, indent=2)
        print("Forced Mercedes target to 100%")
    else:
        print("Settings file not found")

if __name__ == "__main__":
    force_max()