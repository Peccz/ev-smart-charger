import json
import yaml
import os
import shutil
from datetime import datetime

# Paths
BASE_DIR = "/home/peccz/ev_smart_charger"
SETTINGS_YAML = os.path.join(BASE_DIR, "config/settings.yaml")
USER_SETTINGS_JSON = os.path.join(BASE_DIR, "data/user_settings.json")
SECRETS_JSON = os.path.join(BASE_DIR, "data/secrets.json")
BACKUP_DIR = os.path.join(BASE_DIR, "data/backups")

def load_yaml(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return yaml.safe_load(f) or {}
    return {}

def load_json(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f) or {}
    return {}

def save_json(path, data):
    # Atomic write
    temp_path = path + ".tmp"
    with open(temp_path, 'w') as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.rename(temp_path, path)
    print(f"Saved {path}")

def backup_files():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    for fpath in [SETTINGS_YAML, USER_SETTINGS_JSON]:
        if os.path.exists(fpath):
            fname = os.path.basename(fpath)
            backup_path = os.path.join(BACKUP_DIR, f"{fname}_{timestamp}.bak")
            shutil.copy2(fpath, backup_path)
            print(f"Backed up {fname} to {backup_path}")

def migrate():
    print("Starting secrets migration...")
    
    # 1. Load existing data
    yaml_config = load_yaml(SETTINGS_YAML)
    json_config = load_json(USER_SETTINGS_JSON)
    
    # 2. Prepare secrets structure
    secrets = {
        "home_assistant": {
            "url": "",
            "token": ""
        },
        "zaptec": {
            "username": "",
            "password": "",
            "installation_id": "",
            "charger_id": ""
        },
        "nissan": {
            "username": "",
            "password": "",
            "vin": ""
        },
        "flask_secret_key": ""
    }
    
    # 3. Extract from YAML (Zaptec is usually here)
    zap_yaml = yaml_config.get('charger', {}).get('zaptec', {})
    if zap_yaml.get('username'): secrets['zaptec']['username'] = zap_yaml['username']
    if zap_yaml.get('password'): secrets['zaptec']['password'] = zap_yaml['password']
    if zap_yaml.get('installation_id'): secrets['zaptec']['installation_id'] = zap_yaml['installation_id']
    if zap_yaml.get('charger_id'): secrets['zaptec']['charger_id'] = zap_yaml['charger_id']

    # 4. Extract from JSON (HA & Nissan usually here)
    # HA
    if json_config.get('ha_url'): secrets['home_assistant']['url'] = json_config['ha_url']
    if json_config.get('ha_token'): secrets['home_assistant']['token'] = json_config['ha_token']
    
    # Nissan
    if json_config.get('nissan_username'): secrets['nissan']['username'] = json_config['nissan_username']
    if json_config.get('nissan_password'): secrets['nissan']['password'] = json_config['nissan_password']
    if json_config.get('nissan_vin'): secrets['nissan']['vin'] = json_config['nissan_vin']

    # Flask Secret (Reuse existing or generate if we had one stored, otherwise ConfigManager handles it)
    # We won't migrate flask key here as it's in a separate .flask_secret file usually.

    # 5. Save to secrets.json
    save_json(SECRETS_JSON, secrets)
    print("Secrets migrated successfully.")
    
    # 6. Verify
    saved_secrets = load_json(SECRETS_JSON)
    if saved_secrets.get('zaptec', {}).get('username') and saved_secrets.get('home_assistant', {}).get('token'):
        print("Verification PASSED: Critical secrets found in new file.")
    else:
        print("Verification WARNING: Some secrets might be missing. Please check secrets.json manually.")

if __name__ == "__main__":
    backup_files()
    migrate()
