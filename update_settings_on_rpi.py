import json
import os

SETTINGS_PATH = "data/user_settings.json"

def update_settings():
    if not os.path.exists(SETTINGS_PATH):
        print(f"Error: {SETTINGS_PATH} does not exist.")
        return

    try:
        with open(SETTINGS_PATH, 'r') as f:
            settings = json.load(f)
        
        # Update with discovered IDs
        updates = {
            "ha_merc_soc_entity_id": "sensor.urg48t_state_of_charge",
            "ha_merc_plugged_entity_id": "sensor.urg48t_charging_status",
            "mercedes_eqv_climate_entity_id": "button.urg48t_preclimate_start",
            # "mercedes_eqv_lock_entity_id": "", # Leave empty/existing
            
            "ha_nissan_soc_entity_id": "sensor.leaf_battery_level", # Assuming this is correct
            "ha_nissan_plugged_entity_id": "binary_sensor.leaf_plugged_in",
            # "nissan_leaf_climate_entity_id": "" # Leave empty/existing
        }
        
        # Apply updates only if keys don't exist or are empty
        # Actually, user asked to "Fill them in", so let's overwrite/set them.
        for k, v in updates.items():
            settings[k] = v
            print(f"Set {k} = {v}")

        with open(SETTINGS_PATH, 'w') as f:
            json.dump(settings, f, indent=2)
        
        print("Successfully updated user_settings.json")

    except Exception as e:
        print(f"Error updating settings: {e}")

if __name__ == "__main__":
    update_settings()
