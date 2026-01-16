import time
import logging
import subprocess
import requests
import json
import os
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

# Path setup
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from config_manager import ConfigManager, PROJECT_ROOT

# Logging setup
LOG_FILE = PROJECT_ROOT / "ha_watchdog.log"
log_handler = RotatingFileHandler(LOG_FILE, maxBytes=1*1024*1024, backupCount=3)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - WATCHDOG - %(levelname)s - %(message)s',
    handlers=[log_handler, logging.StreamHandler()]
)
logger = logging.getLogger("HA_Watchdog")

# Constants
CHECK_INTERVAL_MINUTES = 30
STALE_THRESHOLD_HOURS = 4
DOCKER_CONTAINER_NAME = "homeassistant"
RESTART_TRACKER_FILE = PROJECT_ROOT / "data" / "last_ha_restart.txt"

def get_last_restart_time():
    if RESTART_TRACKER_FILE.exists():
        try:
            with open(RESTART_TRACKER_FILE, 'r') as f:
                ts = float(f.read().strip())
                return datetime.fromtimestamp(ts, tz=timezone.utc)
        except:
            return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)

def set_last_restart_time():
    RESTART_TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RESTART_TRACKER_FILE, 'w') as f:
        f.write(str(datetime.now(timezone.utc).timestamp()))

def restart_ha():
    logger.warning("🚫 TRIGGERING HOME ASSISTANT RESTART...")
    try:
        # Run docker restart command
        result = subprocess.run(
            ["sudo", "docker", "restart", DOCKER_CONTAINER_NAME], 
            capture_output=True, 
            text=True
        )
        if result.returncode == 0:
            logger.info("✅ Docker restart command successful.")
            set_last_restart_time()
        else:
            logger.error(f"❌ Docker restart failed: {result.stderr}")
    except Exception as e:
        logger.error(f"❌ Failed to run restart command: {e}")

def check_ha_status():
    config = ConfigManager.load_full_config()
    merc_config = config.get('cars', {}).get('mercedes_eqv', {})
    
    ha_url = merc_config.get('ha_url')
    ha_token = merc_config.get('ha_token')
    
    # We focus on the Mercedes SoC sensor as the canary in the coal mine
    sensor_id = merc_config.get('ha_merc_soc_entity_id', 'sensor.urg48t_state_of_charge')

    if not ha_url or not ha_token:
        logger.error("Config missing HA URL/Token. Cannot monitor.")
        return

    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    
    # 1. Check Connectivity
    try:
        url = f"{ha_url.rstrip('/')}/api/states/{sensor_id}"
        resp = requests.get(url, headers=headers, timeout=20)
        
        if resp.status_code != 200:
            logger.warning(f"⚠️ HA Connectivity Issue: Status {resp.status_code}")
            # If we get 401/404/500 repeatedly, we might want to restart.
            # But let's be conservative: only restart on STALE data for now, 
            # unless it's a 502/503 (Bad Gateway/Service Unavailable).
            if resp.status_code in [502, 503, 504]:
                logger.warning("HA appears down (Bad Gateway). Restarting.")
                restart_ha()
            return

        data = resp.json()
        
        # 2. Check Data Freshness
        last_updated_str = data.get('last_updated')
        if last_updated_str:
            last_updated = datetime.fromisoformat(last_updated_str)
            now = datetime.now(timezone.utc)
            age = now - last_updated
            
            logger.info(f"Sensor {sensor_id} age: {age}")
            
            if age > timedelta(hours=STALE_THRESHOLD_HOURS):
                logger.warning(f"🚨 DATA IS STALE! ({age} > {STALE_THRESHOLD_HOURS}h)")
                
                # Check cooldown (don't restart more than once every 12 hours)
                last_restart = get_last_restart_time()
                time_since_restart = now - last_restart
                
                if time_since_restart > timedelta(hours=12):
                    logger.info("Cooldown passed. Initiating restart to fix stale connection.")
                    restart_ha()
                else:
                    logger.info(f"Skipping restart (Cooldown active, last restart {time_since_restart} ago).")
        
    except requests.exceptions.ConnectionError:
        logger.error("❌ Connection Refused to HA. Container might be crashed.")
        # If we can't connect at all, we should probably restart
        restart_ha()
    except Exception as e:
        logger.error(f"Error during check: {e}")

def main():
    logger.info("--- HA Watchdog Started ---")
    while True:
        check_ha_status()
        time.sleep(CHECK_INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    main()
