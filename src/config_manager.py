import yaml
import json
import os
import logging
import secrets

logger = logging.getLogger(__name__)

# Constants
SETTINGS_PATH = "data/user_settings.json"
OVERRIDES_PATH = "data/manual_overrides.json"
STATE_PATH = "data/optimizer_state.json"
MANUAL_STATUS_PATH = "data/manual_status.json"
YAML_CONFIG_PATH = "config/settings.yaml"
FORECAST_HISTORY_FILE = "data/forecast_history.json"
SECRET_KEY_PATH = "data/.flask_secret"

DEFAULT_SETTINGS = {
    "mercedes_eqv_min_soc": 40,
    "mercedes_eqv_max_soc": 80,
    "nissan_leaf_min_soc": 40,
    "nissan_leaf_max_soc": 80,
    "departure_time": "07:00",
    "smart_buffering": True,
    "ha_url": "http://100.100.118.62:8123",
    "ha_token": "",
    "ha_merc_soc_entity_id": "",
    "ha_merc_plugged_entity_id": "",
    "ha_merc_climate_status_id": "",
    "mercedes_eqv_climate_entity_id": "",
    "mercedes_eqv_lock_entity_id": "",
    "mercedes_eqv_odometer_entity_id": "",
    "nissan_leaf_climate_entity_id": "",
    "nissan_leaf_odometer_entity_id": ""
}

class ConfigManager:
    @staticmethod
    def get_flask_secret_key():
        """Gets or generates a persistent secret key for Flask sessions."""
        if os.path.exists(SECRET_KEY_PATH):
            try:
                with open(SECRET_KEY_PATH, 'r') as f:
                    return f.read().strip()
            except Exception as e:
                logger.error(f"Error reading secret key: {e}")
        
        # Generate new key
        new_key = secrets.token_hex(32)
        try:
            os.makedirs(os.path.dirname(SECRET_KEY_PATH), exist_ok=True)
            with open(SECRET_KEY_PATH, 'w') as f:
                f.write(new_key)
            logger.info("Generated and saved new Flask secret key.")
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
                
                # Migration logic for old keys
                if 'mercedes_target' in current_settings and 'mercedes_eqv_max_soc' not in current_settings:
                    current_settings['mercedes_eqv_max_soc'] = current_settings['mercedes_target']
                if 'nissan_target' in current_settings and 'nissan_leaf_max_soc' not in current_settings:
                    current_settings['nissan_leaf_max_soc'] = current_settings['nissan_target']
                if 'mercedes_min_soc' in current_settings and 'mercedes_eqv_min_soc' not in current_settings:
                    current_settings['mercedes_eqv_min_soc'] = current_settings['mercedes_min_soc']
                if 'mercedes_max_soc' in current_settings and 'mercedes_eqv_max_soc' not in current_settings:
                    current_settings['mercedes_eqv_max_soc'] = current_settings['mercedes_max_soc']
                if 'nissan_min_soc' in current_settings and 'nissan_leaf_min_soc' not in current_settings:
                    current_settings['nissan_leaf_min_soc'] = current_settings['nissan_min_soc']
                if 'nissan_max_soc' in current_settings and 'nissan_leaf_max_soc' not in current_settings:
                    current_settings['nissan_leaf_max_soc'] = current_settings['nissan_max_soc']

                return {**DEFAULT_SETTINGS, **current_settings}
        except Exception as e:
            logger.error(f"Error loading user_settings.json: {e}")
            return DEFAULT_SETTINGS.copy()

    @staticmethod
    def save_settings(settings):
        """Saves user settings to JSON."""
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            with open(SETTINGS_PATH, 'w') as f:
                json.dump(settings, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            return False

    @staticmethod
    def load_full_config():
        """Loads YAML config and merges with user settings."""
        base_config = {}
        if os.path.exists(YAML_CONFIG_PATH):
            try:
                with open(YAML_CONFIG_PATH, 'r') as f:
                    base_config = yaml.safe_load(f)
            except Exception as e:
                logger.error(f"Error loading settings.yaml: {e}")
        
        user_settings = ConfigManager.get_settings()

        # Ensure sections exist
        if 'optimization' not in base_config:
            base_config['optimization'] = {'price_buffer_threshold': 0.10, 'planning_horizon_days': 3}
        if 'cars' not in base_config:
            base_config['cars'] = {}
        
        # --- Mercedes Config Merge ---
        merc_base = base_config['cars'].get('mercedes_eqv', {})
        base_config['cars']['mercedes_eqv'] = {
            'capacity_kwh': merc_base.get('capacity_kwh', 90),
            'max_charge_kw': merc_base.get('max_charge_kw', merc_base.get('max_charge_rate_kw', 11)),
            'vin': merc_base.get('vin'),
            'target_soc': user_settings.get('mercedes_eqv_target', user_settings.get('mercedes_target', merc_base.get('target_soc', 80))),
            'min_soc': user_settings.get('mercedes_eqv_min_soc', 40),
            'max_soc': user_settings.get('mercedes_eqv_max_soc', 80),
            'ha_url': user_settings.get('ha_url'),
            'ha_token': user_settings.get('ha_token'),
            'ha_merc_soc_entity_id': user_settings.get('ha_merc_soc_entity_id'),
            'ha_merc_plugged_entity_id': user_settings.get('ha_merc_plugged_entity_id'),
            'climate_entity_id': user_settings.get('mercedes_eqv_climate_entity_id'),
            'climate_status_id': user_settings.get('mercedes_eqv_climate_status_id'),
            'lock_entity_id': user_settings.get('mercedes_eqv_lock_entity_id'),
            'odometer_entity_id': user_settings.get('mercedes_eqv_odometer_entity_id')
        }

        # --- Nissan Config Merge ---
        nis_base = base_config['cars'].get('nissan_leaf', {})
        base_config['cars']['nissan_leaf'] = {
            'capacity_kwh': nis_base.get('capacity_kwh', 40),
            'max_charge_kw': nis_base.get('max_charge_kw', nis_base.get('max_charge_rate_kw', 3.7)), # Default 3.7 kW
            'vin': user_settings.get('nissan_vin', nis_base.get('vin')),
            'target_soc': user_settings.get('nissan_leaf_target', user_settings.get('nissan_target', nis_base.get('target_soc', 80))),
            'min_soc': user_settings.get('nissan_leaf_min_soc', 40),
            'max_soc': user_settings.get('nissan_leaf_max_soc', 80),
            'ha_url': user_settings.get('ha_url'),
            'ha_token': user_settings.get('ha_token'),
            'ha_nissan_soc_entity_id': user_settings.get('ha_nissan_soc_entity_id'),
            'ha_nissan_plugged_entity_id': user_settings.get('ha_nissan_plugged_entity_id'),
            'ha_nissan_range_entity_id': user_settings.get('ha_nissan_range_entity_id'),
            'climate_entity_id': user_settings.get('nissan_leaf_climate_entity_id'),
            'odometer_entity_id': user_settings.get('nissan_leaf_odometer_entity_id')
        }
        
        # Inject grid config if missing (for spot_price service)
        if 'grid' not in base_config:
            base_config['grid'] = {'region': 'SE3'}
            
        # Inject location if missing (for weather service)
        if 'location' not in base_config:
            base_config['location'] = {'latitude': 59.5196, 'longitude': 17.9285}

        return base_config
