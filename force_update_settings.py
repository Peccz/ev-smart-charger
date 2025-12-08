import json
import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SETTINGS_PATH = "data/user_settings.json"

# HARDCODED SENSORS
SENSORS = {
    # Mercedes
    "ha_merc_soc_entity_id": "sensor.urg48t_state_of_charge",
    "ha_merc_plugged_entity_id": "sensor.urg48t_range_electric",
    "ha_merc_range_entity_id": "sensor.urg48t_range_electric",
    "mercedes_eqv_odometer_entity_id": "sensor.urg48t_odometer",
    "mercedes_eqv_climate_entity_id": "button.urg48t_preclimate_start",
    "mercedes_eqv_lock_entity_id": "lock.urg48t_lock", # Assuming lock domain, if sensor only, control won't work but status might

    # Nissan
    "ha_nissan_soc_entity_id": "sensor.leaf_battery_level",
    "ha_nissan_plugged_entity_id": "binary_sensor.leaf_plugged_in",
    "ha_nissan_range_entity_id": "sensor.leaf_range_ac_on",
    # "nissan_leaf_odometer_entity_id": "sensor.leaf_odometer", # Uncomment if known
    "nissan_leaf_climate_entity_id": "switch.leaf_climate_control", # Common for Leaf integration
    "nissan_leaf_update_entity_id": "button.leaf_update_data"
}

def force_update():
    if not os.path.exists(SETTINGS_PATH):
        logger.error(f"{SETTINGS_PATH} not found!")
        return

    try:
        with open(SETTINGS_PATH, 'r') as f:
            data = json.load(f)
        
        logger.info("Updating settings with hardcoded sensors...")
        for key, value in SENSORS.items():
            data[key] = value
            logger.info(f"  Set {key} = {value}")
            
        # Atomic write
        temp_path = SETTINGS_PATH + ".tmp"
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.rename(temp_path, SETTINGS_PATH)
        logger.info("Settings updated successfully.")
        
    except Exception as e:
        logger.error(f"Failed to update settings: {e}")

if __name__ == "__main__":
    force_update()
