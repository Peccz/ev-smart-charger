import yaml
import json
import logging
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

# Get absolute project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Constants - ALL PATHS ARE Path OBJECTS
SETTINGS_PATH = PROJECT_ROOT / "data" / "user_settings.json"
OVERRIDES_PATH = PROJECT_ROOT / "data" / "manual_overrides.json"
STATE_PATH = PROJECT_ROOT / "data" / "optimizer_state.json"
MANUAL_STATUS_PATH = PROJECT_ROOT / "data" / "manual_status.json"
YAML_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"
SECRETS_PATH = PROJECT_ROOT / "data" / "secrets.json"
FORECAST_HISTORY_FILE = PROJECT_ROOT / "data" / "forecast_history.json"
PRICE_HISTORY_CACHE_FILE = PROJECT_ROOT / "data" / "price_history_cache.json"
SECRET_KEY_PATH = PROJECT_ROOT / "data" / ".flask_secret"
DATABASE_PATH = PROJECT_ROOT / "data" / "ev_charger.db"

DEFAULT_SETTINGS = {
    "mercedes_eqv_min_soc": 60,
    "mercedes_eqv_max_soc": 90,
    "nissan_leaf_min_soc": 60,
    "nissan_leaf_max_soc": 90,
    "departure_time": "07:00",
    "smart_buffering": True,
    "daily_charging_enabled": True,
    "grid_fee_sek_per_kwh": 0.25,
    "energy_tax_sek_per_kwh": 0.36, 
    "retailer_fee_sek_per_kwh": 0.05,
    "vat_rate": 0.25
}

# DEFAULT SENSOR CONFIGURATION (Fallbacks)
DEFAULT_SENSORS = {
    "mercedes_eqv": {
        "ha_soc_id": "sensor.urg48t_state_of_charge",
        "ha_plugged_id": "sensor.urg48t_range_electric",
        "ha_climate_id": "button.urg48t_preclimate_start",
        "ha_climate_status_id": "binary_sensor.urg48t_preclimate_status",
        "ha_odometer_id": "sensor.urg48t_odometer"
    },
    "nissan_leaf": {
        "ha_soc_id": "sensor.leaf_battery_level",
        "ha_plugged_id": "binary_sensor.leaf_plugged_in",
        "ha_climate_id": "climate.leaf_climate",
        "ha_last_updated_id": "sensor.leaf_last_updated",
        "ha_update_id": "button.leaf_update_data",
        "ha_odometer_id": "sensor.leaf_odometer"
    }
}

class ConfigManager:
    @staticmethod
    def get_flask_secret_key():
        if SECRET_KEY_PATH.exists():
            try:
                return SECRET_KEY_PATH.read_text().strip()
            except Exception as e:
                logger.error(f"Error reading secret key: {e}")
        
        new_key = secrets.token_hex(32)
        try:
            SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
            SECRET_KEY_PATH.write_text(new_key)
        except Exception as e:
            logger.error(f"Error saving secret key: {e}")
        
        return new_key

    @staticmethod
    def get_settings():
        """Loads user settings from JSON, merged with defaults."""
        if not SETTINGS_PATH.exists():
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
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            # Remove keys that match defaults to keep the file lean
            to_save = {k: v for k, v in settings.items() if k not in DEFAULT_SETTINGS or settings[k] != DEFAULT_SETTINGS[k]}
            
            temp_path = SETTINGS_PATH.with_suffix(".tmp")
            with open(temp_path, 'w') as f:
                json.dump(to_save, f, indent=2)
            temp_path.replace(SETTINGS_PATH)
            return True
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            return False

    @staticmethod
    def load_full_config():
        """Loads YAML config, merges with secrets and user settings."""
        base_config = {}
        
        if YAML_CONFIG_PATH.exists():
            try:
                with open(YAML_CONFIG_PATH, 'r') as f:
                    base_config = yaml.safe_load(f) or {}
            except Exception as e:
                logger.error(f"Error loading settings.yaml: {e}")
        
        secrets_data = {}
        if SECRETS_PATH.exists():
            try:
                with open(SECRETS_PATH, 'r') as f:
                    secrets_data = json.load(f)
            except Exception as e:
                logger.error(f"Error loading secrets.json: {e}")
        
        # Merge Zaptec Secrets
        if secrets_data.get('zaptec'):
            base_config.setdefault('charger', {}).setdefault('zaptec', {}).update(secrets_data['zaptec'])
            
        ha_secrets = secrets_data.get('home_assistant', {})
        user_settings = ConfigManager.get_settings()

        def get_val(key, default=None):
            user_val = user_settings.get(key)
            return user_val if user_val not in [None, ""] else default

        # Global Optimization settings
        opt_cfg = base_config.get('optimization', {})
        base_config['optimization'] = {
            'price_buffer_threshold': opt_cfg.get('price_buffer_threshold', 0.10),
            'planning_horizon_days': opt_cfg.get('planning_horizon_days', 3),
            'forecast_wind_penalty': opt_cfg.get('forecast_wind_penalty', 0.03),
            'forecast_solar_discount': opt_cfg.get('forecast_solar_discount', 0.0002),
            'forecast_temp_penalty': opt_cfg.get('forecast_temp_penalty', 0.01),
            'forecast_winter_bias': opt_cfg.get('forecast_winter_bias', 1.10)
        }

        # --- Vehicle Helper ---
        def merge_vehicle(key_id, name_fallback):
            v_base = base_config.get('cars', {}).get(key_id, {})
            v_secrets = secrets_data.get('nissan' if 'nissan' in key_id else 'mercedes', {})
            defaults = DEFAULT_SENSORS.get(key_id, {})
            
            return {
                'capacity_kwh': v_base.get('capacity_kwh', 90 if 'mercedes' in key_id else 40),
                'max_charge_kw': v_base.get('max_charge_kw', 11 if 'mercedes' in key_id else 3.7),
                'vin': v_secrets.get('vin', v_base.get('vin', '')),
                'target_soc': get_val(f'{key_id}_target', 80),
                'min_soc': get_val(f'{key_id}_min_soc', 40),
                'max_soc': get_val(f'{key_id}_max_soc', 80),
                'ha_url': ha_secrets.get('url', v_base.get('ha_url', 'http://100.100.118.62:8123')),
                'ha_token': ha_secrets.get('token', v_base.get('ha_token')),
                
                # Dynamic Entity Mapping (Priority: settings.yaml -> fallback)
                'ha_merc_soc_entity_id': v_base.get('ha_soc_id', defaults.get('ha_soc_id')),
                'ha_nissan_soc_entity_id': v_base.get('ha_soc_id', defaults.get('ha_soc_id')),
                'ha_merc_plugged_entity_id': v_base.get('ha_plugged_id', defaults.get('ha_plugged_id')),
                'ha_nissan_plugged_entity_id': v_base.get('ha_plugged_id', defaults.get('ha_plugged_id')),
                'ha_nissan_range_entity_id': v_base.get('ha_range_id', 'sensor.leaf_range_ac_on'),
                'ha_nissan_last_updated_id': v_base.get('ha_last_updated_id', defaults.get('ha_last_updated_id')),
                'climate_entity_id': v_base.get('ha_climate_id', defaults.get('ha_climate_id')),
                'climate_status_id': v_base.get('ha_climate_status_id', defaults.get('ha_climate_status_id')),
                'odometer_entity_id': v_base.get('ha_odometer_id', defaults.get('ha_odometer_id')),
                'update_entity_id': v_base.get('ha_update_id', defaults.get('ha_update_id')),
                
                'username': v_secrets.get('username', get_val(f'{key_id}_username')),
                'password': v_secrets.get('password', get_val(f'{key_id}_password'))
            }

        base_config['cars'] = {
            'mercedes_eqv': merge_vehicle('mercedes_eqv', 'Mercedes EQV'),
            'nissan_leaf': merge_vehicle('nissan_leaf', 'Nissan Leaf')
        }
        
        # Add shared fees to config
        for fee_key in ['grid_fee_sek_per_kwh', 'energy_tax_sek_per_kwh', 'retailer_fee_sek_per_kwh', 'vat_rate']:
            base_config[fee_key] = get_val(fee_key, DEFAULT_SETTINGS[fee_key])

        base_config.setdefault('grid', {'region': 'SE3'})
        base_config.setdefault('location', {'latitude': 59.5196, 'longitude': 17.9285})

        return base_config
