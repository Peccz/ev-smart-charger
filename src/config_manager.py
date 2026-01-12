import yaml
import json
import os
import logging
import secrets

logger = logging.getLogger(__name__)

# Get absolute project root directory
# This file is in src/, so project root is one level up
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Constants - ALL PATHS ARE ABSOLUTE
SETTINGS_PATH = os.path.join(PROJECT_ROOT, "data", "user_settings.json")
OVERRIDES_PATH = os.path.join(PROJECT_ROOT, "data", "manual_overrides.json")
STATE_PATH = os.path.join(PROJECT_ROOT, "data", "optimizer_state.json")
MANUAL_STATUS_PATH = os.path.join(PROJECT_ROOT, "data", "manual_status.json")
YAML_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "settings.yaml")
SECRETS_PATH = os.path.join(PROJECT_ROOT, "data", "secrets.json")
FORECAST_HISTORY_FILE = os.path.join(PROJECT_ROOT, "data", "forecast_history.json")
PRICE_HISTORY_CACHE_FILE = os.path.join(PROJECT_ROOT, "data", "price_history_cache.json")
SECRET_KEY_PATH = os.path.join(PROJECT_ROOT, "data", ".flask_secret")
DATABASE_PATH = os.path.join(PROJECT_ROOT, "data", "ev_charger.db")

DEFAULT_SETTINGS = {
    "mercedes_eqv_min_soc": 60,
    "mercedes_eqv_max_soc": 90,
    "nissan_leaf_min_soc": 60,
    "nissan_leaf_max_soc": 90,
    "departure_time": "07:00",
    "smart_buffering": True,
    "daily_charging_enabled": True  # Charge daily during cheapest hours
}

# STRIKT KONFIGURATION AV SENSORER
# Dessa värden skriver över allt annat för att garantera funktion.
#
# ARCHITECTURAL NOTE (Fas 2 Review):
# Hårdkodade sensor-ID:n garanterar drift men är inte flexibla.
# Alternativ framtida lösning: Flytta till secrets.json under "hardware" sektion
# för bättre separation mellan användarsättningar och hårdvaru-specifik config.
# Behålls som hårdkodade för nu för driftstabilitet.
HARDCODED_SENSORS = {
    # Mercedes EQV
    "ha_merc_soc_entity_id": "sensor.urg48t_state_of_charge",
    "ha_merc_plugged_entity_id": "sensor.urg48t_range_electric", # Logic based on chargingstatus attr
    "ha_merc_range_entity_id": "sensor.urg48t_range_electric",
    "mercedes_eqv_odometer_entity_id": "sensor.urg48t_odometer",
    "mercedes_eqv_climate_entity_id": "button.urg48t_preclimate_start",
    "mercedes_eqv_climate_status_id": "binary_sensor.urg48t_preclimate_status", # If available

    # Nissan Leaf
    "ha_nissan_soc_entity_id": "sensor.leaf_battery_level",
    "ha_nissan_plugged_entity_id": "binary_sensor.leaf_plugged_in",
    "ha_nissan_range_entity_id": "sensor.leaf_range_ac_on",
    "ha_nissan_last_updated_id": "sensor.leaf_last_updated",
    "nissan_leaf_climate_entity_id": "climate.leaf_climate",
    "nissan_leaf_update_entity_id": "button.leaf_update_data",
    "nissan_leaf_odometer_entity_id": "sensor.leaf_odometer",
    "nissan_leaf_location_id": "device_tracker.leaf_location",

    # Home Sensors (Timmerflotte)
    "ha_temp_sensor_id": "sensor.timmerflotte_temp_hmd_sensor_temperature", # Uppe
    "ha_humidity_sensor_id": "sensor.timmerflotte_temp_hmd_sensor_humidity"
}

class ConfigManager:
    @staticmethod
    def get_flask_secret_key():
        if os.path.exists(SECRET_KEY_PATH):
            try:
                with open(SECRET_KEY_PATH, 'r') as f:
                    return f.read().strip()
            except Exception as e:
                logger.error(f"Error reading secret key: {e}")
        
        new_key = secrets.token_hex(32)
        try:
            os.makedirs(os.path.dirname(SECRET_KEY_PATH), exist_ok=True)
            with open(SECRET_KEY_PATH, 'w') as f:
                f.write(new_key)
        except Exception as e:
            logger.error(f"Error saving secret key: {e}")
        
        return new_key

    @staticmethod
    def get_settings():
        """Loads user settings from JSON, merged with defaults."""
        if not os.path.exists(SETTINGS_PATH):
            return DEFAULT_SETTINGS.copy()
        try:
            with open(SETTINGS_PATH, 'r') as f:
                current_settings = json.load(f)
                # Merge defaults -> user settings -> hardcoded sensors
                # This ensures get_settings() also returns the correct sensor IDs for the UI
                return {**DEFAULT_SETTINGS, **current_settings, **HARDCODED_SENSORS}
        except Exception as e:
            logger.error(f"Error loading user_settings.json: {e}")
            return DEFAULT_SETTINGS.copy()

    @staticmethod
    def save_settings(settings):
        """Saves user settings to JSON."""
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            # We filter out the hardcoded sensors before saving to keep the file clean, 
            # although saving them doesn't hurt since they are enforced on load.
            to_save = {k: v for k, v in settings.items() if k not in HARDCODED_SENSORS}
            
            temp_path = SETTINGS_PATH + ".tmp"
            with open(temp_path, 'w') as f:
                json.dump(to_save, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.rename(temp_path, SETTINGS_PATH)
            return True
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            return False

    @staticmethod
    def load_full_config():
        """Loads YAML config, merges with secrets and user settings."""
        base_config = {}
        
        if os.path.exists(YAML_CONFIG_PATH):
            try:
                with open(YAML_CONFIG_PATH, 'r') as f:
                    base_config = yaml.safe_load(f) or {}
            except Exception as e:
                logger.error(f"Error loading settings.yaml: {e}")
        
        secrets = {}
        if os.path.exists(SECRETS_PATH):
            try:
                with open(SECRETS_PATH, 'r') as f:
                    secrets = json.load(f)
            except Exception as e:
                logger.error(f"Error loading secrets.json: {e}")
        
        # Merge Secrets
        if secrets.get('zaptec'):
            if 'charger' not in base_config: base_config['charger'] = {}
            if 'zaptec' not in base_config['charger']: base_config['charger']['zaptec'] = {}
            base_config['charger']['zaptec'].update(secrets['zaptec'])
            
        ha_secrets = secrets.get('home_assistant', {})
        user_settings = ConfigManager.get_settings() # This now includes HARDCODED_SENSORS

        def get_val(key, default=None):
            user_val = user_settings.get(key)
            if user_val is not None and user_val != "":
                return user_val
            return default

        if 'optimization' not in base_config:
            base_config['optimization'] = {'price_buffer_threshold': 0.10, 'planning_horizon_days': 3}
        if 'cars' not in base_config:
            base_config['cars'] = {}
        
        # --- Mercedes Config Merge ---
        merc_base = base_config['cars'].get('mercedes_eqv', {})
        base_config['cars']['mercedes_eqv'] = {
            'capacity_kwh': merc_base.get('capacity_kwh', 90),
            'max_charge_kw': merc_base.get('max_charge_kw', 11),
            'vin': merc_base.get('vin'),
            'target_soc': get_val('mercedes_eqv_target', 80),
            'min_soc': get_val('mercedes_eqv_min_soc', 40),
            'max_soc': get_val('mercedes_eqv_max_soc', 80),
            'ha_url': ha_secrets.get('url', get_val('ha_url', merc_base.get('ha_url'))),
            'ha_token': ha_secrets.get('token', get_val('ha_token', merc_base.get('ha_token'))),
            
            # HARDCODED ENFORCEMENT
            'ha_merc_soc_entity_id': HARDCODED_SENSORS['ha_merc_soc_entity_id'],
            'ha_merc_plugged_entity_id': HARDCODED_SENSORS['ha_merc_plugged_entity_id'],
            'climate_entity_id': HARDCODED_SENSORS['mercedes_eqv_climate_entity_id'],
            'climate_status_id': HARDCODED_SENSORS.get('mercedes_eqv_climate_status_id'),
            'odometer_entity_id': HARDCODED_SENSORS['mercedes_eqv_odometer_entity_id']
        }

        # --- Nissan Config Merge ---
        nis_base = base_config['cars'].get('nissan_leaf', {})
        nis_secrets = secrets.get('nissan', {})
        
        base_config['cars']['nissan_leaf'] = {
            'capacity_kwh': nis_base.get('capacity_kwh', 40),
            'max_charge_kw': nis_base.get('max_charge_kw', 3.7),
            'vin': nis_secrets.get('vin', get_val('nissan_vin', nis_base.get('vin'))),
            'target_soc': get_val('nissan_leaf_target', 80),
            'min_soc': get_val('nissan_leaf_min_soc', 40),
            'max_soc': get_val('nissan_leaf_max_soc', 80),
            'ha_url': ha_secrets.get('url', get_val('ha_url', nis_base.get('ha_url'))),
            'ha_token': ha_secrets.get('token', get_val('ha_token', nis_base.get('ha_token'))),
            
            # HARDCODED ENFORCEMENT
            'ha_nissan_soc_entity_id': HARDCODED_SENSORS['ha_nissan_soc_entity_id'],
            'ha_nissan_plugged_entity_id': HARDCODED_SENSORS['ha_nissan_plugged_entity_id'],
            'ha_nissan_range_entity_id': HARDCODED_SENSORS['ha_nissan_range_entity_id'],
            'ha_nissan_last_updated_id': HARDCODED_SENSORS.get('ha_nissan_last_updated_id'),
            'climate_entity_id': HARDCODED_SENSORS['nissan_leaf_climate_entity_id'],
            'odometer_entity_id': HARDCODED_SENSORS.get('nissan_leaf_odometer_entity_id'),
            'location_id': HARDCODED_SENSORS.get('nissan_leaf_location_id'),
            'update_entity_id': HARDCODED_SENSORS['nissan_leaf_update_entity_id'],
            'ha_nissan_charging_entity_id': nis_base.get('ha_nissan_charging_entity_id'), # New field passed through
            
            'username': nis_secrets.get('username', get_val('nissan_username')),
            'password': nis_secrets.get('password', get_val('nissan_password'))
        }
        
        if 'grid' not in base_config:
            base_config['grid'] = {'region': 'SE3'}
        if 'location' not in base_config:
            base_config['location'] = {'latitude': 59.5196, 'longitude': 17.9285}

        return base_config
