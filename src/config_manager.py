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
SECRETS_PATH = "data/secrets.json"
FORECAST_HISTORY_FILE = "data/forecast_history.json"
SECRET_KEY_PATH = "data/.flask_secret"

DEFAULT_SETTINGS = {
    "mercedes_eqv_min_soc": 40,
    "mercedes_eqv_max_soc": 80,
    "nissan_leaf_min_soc": 40,
    "nissan_leaf_max_soc": 80,
    "departure_time": "07:00",
    "smart_buffering": True,
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
                return {**DEFAULT_SETTINGS, **current_settings}
        except Exception as e:
            logger.error(f"Error loading user_settings.json: {e}")
            return DEFAULT_SETTINGS.copy()

    @staticmethod
    def save_settings(settings):
        """Saves user settings to JSON."""
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            # Atomic write
            temp_path = SETTINGS_PATH + ".tmp"
            with open(temp_path, 'w') as f:
                json.dump(settings, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.rename(temp_path, SETTINGS_PATH)
            return True
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            return False

    @staticmethod
    def _deep_merge(dict1, dict2):
        """Recursive merge of dictionaries."""
        for key, value in dict2.items():
            if key in dict1 and isinstance(dict1[key], dict) and isinstance(value, dict):
                ConfigManager._deep_merge(dict1[key], value)
            else:
                dict1[key] = value
        return dict1

    @staticmethod
    def load_full_config():
        """Loads YAML config, merges with secrets and user settings."""
        base_config = {}
        
        # 1. Load base YAML (Structure & Defaults)
        if os.path.exists(YAML_CONFIG_PATH):
            try:
                with open(YAML_CONFIG_PATH, 'r') as f:
                    base_config = yaml.safe_load(f) or {}
            except Exception as e:
                logger.error(f"Error loading settings.yaml: {e}")
        
        # 2. Load Secrets (Overrides base config credentials)
        secrets = {}
        if os.path.exists(SECRETS_PATH):
            try:
                with open(SECRETS_PATH, 'r') as f:
                    secrets = json.load(f)
            except Exception as e:
                logger.error(f"Error loading secrets.json: {e}")
        
        # 3. Merge Secrets into Base Config
        # Map flat secrets structure to nested config structure
        if secrets.get('zaptec'):
            if 'charger' not in base_config: base_config['charger'] = {}
            if 'zaptec' not in base_config['charger']: base_config['charger']['zaptec'] = {}
            base_config['charger']['zaptec'].update(secrets['zaptec'])
            
        # HA secrets are a bit tricky as they are often used in user_settings or main config
        # Let's prioritize secrets for HA
        ha_secrets = secrets.get('home_assistant', {})
        
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
            # HA Credentials Priority: 1. Secrets, 2. User Settings, 3. Base Config (should be empty)
            'ha_url': ha_secrets.get('url', user_settings.get('ha_url')),
            'ha_token': ha_secrets.get('token', user_settings.get('ha_token')),
            'ha_merc_soc_entity_id': user_settings.get('ha_merc_soc_entity_id'),
            'ha_merc_plugged_entity_id': user_settings.get('ha_merc_plugged_entity_id'),
            'climate_entity_id': user_settings.get('mercedes_eqv_climate_entity_id'),
            'climate_status_id': user_settings.get('mercedes_eqv_climate_status_id'),
            'lock_entity_id': user_settings.get('mercedes_eqv_lock_entity_id'),
            'odometer_entity_id': user_settings.get('mercedes_eqv_odometer_entity_id')
        }

        # --- Nissan Config Merge ---
        nis_base = base_config['cars'].get('nissan_leaf', {})
        # Check secrets for Nissan
        nis_secrets = secrets.get('nissan', {})
        
        base_config['cars']['nissan_leaf'] = {
            'capacity_kwh': nis_base.get('capacity_kwh', 40),
            'max_charge_kw': nis_base.get('max_charge_kw', nis_base.get('max_charge_rate_kw', 3.7)),
            'vin': nis_secrets.get('vin', user_settings.get('nissan_vin', nis_base.get('vin'))),
            'target_soc': user_settings.get('nissan_leaf_target', user_settings.get('nissan_target', nis_base.get('target_soc', 80))),
            'min_soc': user_settings.get('nissan_leaf_min_soc', 40),
            'max_soc': user_settings.get('nissan_leaf_max_soc', 80),
            # HA Credentials
            'ha_url': ha_secrets.get('url', user_settings.get('ha_url')),
            'ha_token': ha_secrets.get('token', user_settings.get('ha_token')),
            
            'ha_nissan_soc_entity_id': user_settings.get('ha_nissan_soc_entity_id'),
            'ha_nissan_plugged_entity_id': user_settings.get('ha_nissan_plugged_entity_id'),
            'ha_nissan_range_entity_id': user_settings.get('ha_nissan_range_entity_id'),
            'climate_entity_id': user_settings.get('nissan_leaf_climate_entity_id'),
            'odometer_entity_id': user_settings.get('nissan_leaf_odometer_entity_id'),
            
            # Nissan Legacy Credentials (if we ever use direct API again)
            'username': nis_secrets.get('username', user_settings.get('nissan_username')),
            'password': nis_secrets.get('password', user_settings.get('nissan_password'))
        }
        
        # Inject grid/location if missing
        if 'grid' not in base_config:
            base_config['grid'] = {'region': 'SE3'}
        if 'location' not in base_config:
            base_config['location'] = {'latitude': 59.5196, 'longitude': 17.9285}

        return base_config