class ZaptecMonitor:
    def __init__(self, config):
        self.username = config['username']
        self.password = config['password']
        self.installation_id = config['installation_id']
        self.charger_id = config.get('charger_id') # New: specific charger ID
        self.api_url = "https://api.zaptec.com/api"
        self.token = None
        self.token_expires = 0
    
    def _authenticate(self):
        if self.token and time.time() < self.token_expires:
            return True

        url = "https://api.zaptec.com/oauth/token"
        payload = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password
        }
        try:
            response = requests.post(url, data=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            self.token = data['access_token']
            self.token_expires = time.time() + data['expires_in'] - 60 # Buffer
            return True
        except Exception as e:
            print(f"Zaptec Auth Error: {e}", flush=True)
            self.token = None
            return False

    def get_status(self):
        target_id = self.charger_id if self.charger_id else self.installation_id
        if not target_id:
            print("Zaptec: No charger_id or installation_id configured.", flush=True)
            return {"operating_mode": "UNKNOWN_ID", "power_kw": 0.0, "is_charging": False}
        
        if not self._authenticate():
            return {"operating_mode": "AUTH_FAILED", "power_kw": 0.0, "is_charging": False}

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        url = f"{self.api_url}/chargers/{target_id}/state"
        
        try:
            print(f"Zaptec: Attempting to get status for ID: {target_id} from URL: {url}", flush=True)
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            operating_mode = "UNKNOWN"
            power_kw = 0.0
            is_charging = False

            for obs in data:
                if obs['stateId'] == 506: # Operating Mode
                    mode_val = int(obs['valueAsString'])
                    if mode_val == 1: operating_mode = "DISCONNECTED"
                    elif mode_val == 2: operating_mode = "CONNECTED_WAITING"
                    elif mode_val == 3: operating_mode = "CHARGING"
                    
                    if mode_val == 3: is_charging = True
                elif obs['stateId'] == 510: # Total Power (W)
                    power_kw = float(obs['valueAsString']) / 1000.0

            return {
                "operating_mode": operating_mode,
                "power_kw": power_kw,
                "is_charging": is_charging
            }

        except requests.exceptions.HTTPError as e:
            print(f"Zaptec Status HTTP Error ({target_id}): {e.response.status_code} - {e.response.text}", flush=True)
            return {"operating_mode": "API_ERROR", "power_kw": 0.0, "is_charging": False}
        except Exception as e:
            print(f"Zaptec Status Error ({target_id}): {e}", flush=True)
            return {"operating_mode": "API_ERROR", "power_kw": 0.0, "is_charging": False}

def get_settings():
    if not os.path.exists(SETTINGS_PATH):
        return None
    with open(SETTINGS_PATH, 'r') as f:
        return json.load(f)

def load_base_config():
    """Loads base YAML config."""
    if not os.path.exists(YAML_CONFIG_PATH):
        return {}
    try:
        with open(YAML_CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading settings.yaml: {e}", flush=True)
        return {}

def get_ha_states(base_url, token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{base_url.rstrip('/')}/api/states"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching HA states: {e}", flush=True)
        return []

def main():
    user_settings = get_settings()
    if not user_settings:
        print("User settings not found. Cannot monitor HA.", flush=True)
        ha_monitor_enabled = False
    else:
        ha_base_url = user_settings.get("ha_url")
        ha_token = user_settings.get("ha_token")
        if not ha_base_url or not ha_token:
            print("HA credentials incomplete. HA monitor disabled.", flush=True)
            ha_monitor_enabled = False
        else:
            ha_monitor_enabled = True

    base_config = load_base_config()
    zaptec_config = base_config.get('charger', {}).get('zaptec', {})
    
    # Check if we have enough info for Zaptec Monitor
    if not (zaptec_config.get('username') and zaptec_config.get('password') and 
            (zaptec_config.get('installation_id') or zaptec_config.get('charger_id'))): # Either ID is enough
        print("Zaptec credentials/IDs incomplete. Zaptec monitor disabled.", flush=True)
        zaptec_monitor_enabled = False
    else:
        zaptec_monitor_enabled = True
        zaptec_monitor = ZaptecMonitor(zaptec_config)

    if not ha_monitor_enabled and not zaptec_monitor_enabled:
        print("No monitoring targets configured. Exiting.", flush=True)
        return

    print(f"Starting monitor. Logging changes to {LOG_FILE}...", flush=True)
    
    # Filter for interesting HA entities
    ha_keywords = ["urg48t", "leaf"]
    
    last_ha_states = {}
    last_zaptec_status = {}

    # Initial fetch
    print("Fetching initial state...", flush=True)
    if ha_monitor_enabled:
        ha_states_list = get_ha_states(ha_base_url, ha_token)
        for entity in ha_states_list:
            eid = entity['entity_id']
            if any(k in eid for k in ha_keywords):
                last_ha_states[eid] = entity
    
    if zaptec_monitor_enabled:
        last_zaptec_status = zaptec_monitor.get_status()


    with open(LOG_FILE, "a") as f:
        f.write(f"--- Monitoring started at {datetime.now()} ---\n")

    while True:
        time.sleep(5) # Check every 5 seconds
        timestamp = datetime.now().strftime("%H:%M:%S")
        changes_found = False

        # --- Monitor HA Entities ---
        if ha_monitor_enabled:
            current_ha_states_list = get_ha_states(ha_base_url, ha_token)
            current_ha_states_map = {}
            ha_interesting_attrs = ['charging', 'pluggedIn', 'chargingstatus', 'chargingactive']

            for entity in current_ha_states_list:
                eid = entity['entity_id']
                if not any(k in eid for k in ha_keywords):
                    continue
                
                current_ha_states_map[eid] = entity
                
                if eid in last_ha_states:
                    old = last_ha_states[eid]
                    if old['state'] != entity['state']:
                        msg = f"[{timestamp}] HA {eid}: STATE changed '{old['state']}' -> '{entity['state']}'"
                        print(msg, flush=True)
                        with open(LOG_FILE, "a") as f: f.write(msg + "\n", flush=True)
                        changes_found = True
                    
                    for attr in ha_interesting_attrs:
                        old_val = old.get('attributes', {}).get(attr)
                        new_val = entity.get('attributes', {}).get(attr)
                        if old_val != new_val:
                            msg = f"[{timestamp}] HA {eid}: ATTR '{attr}' changed '{old_val}' -> '{new_val}'"
                            print(msg, flush=True)
                            with open(LOG_FILE, "a") as f: f.write(msg + "\n", flush=True)
                            changes_found = True
                else:
                    msg = f"[{timestamp}] HA New entity found: {eid} = {entity['state']}"
                    print(msg, flush=True)
                    with open(LOG_FILE, "a") as f: f.write(msg + "\n", flush=True)
            last_ha_states = current_ha_states_map

        # --- Monitor Zaptec Charger ---
        if zaptec_monitor_enabled:
            current_zaptec_status = zaptec_monitor.get_status()
            zaptec_interesting_keys = ["operating_mode", "power_kw", "is_charging"]
            
            for key in zaptec_interesting_keys:
                old_val = last_zaptec_status.get(key)
                new_val = current_zaptec_status.get(key)
                
                if old_val != new_val:
                    msg = f"[{timestamp}] Zaptec {key}: changed '{old_val}' -> '{new_val}'"
                    print(msg, flush=True)
                    with open(LOG_FILE, "a") as f: f.write(msg + "\n", flush=True)
                    changes_found = True
            last_zaptec_status = current_zaptec_status

if __name__ == "__main__":
    main()


