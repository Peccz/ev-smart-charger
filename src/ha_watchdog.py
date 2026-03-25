import time
import logging
import subprocess
import requests
import json
import os
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Path setup
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from config_manager import ConfigManager, PROJECT_ROOT, STATE_PATH
from src.connectors.home_assistant import HomeAssistantClient

# Logging setup
LOG_FILE = PROJECT_ROOT / "system_monitor.log"
log_handler = RotatingFileHandler(LOG_FILE, maxBytes=1*1024*1024, backupCount=3)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - MONITOR - %(levelname)s - %(message)s',
    handlers=[log_handler, logging.StreamHandler()]
)
logger = logging.getLogger("SystemMonitor")

# Constants
CHECK_INTERVAL_SECONDS = 60  # Check every minute
STALE_STATE_THRESHOLD_MINUTES = 10 # Restart core service if state file is old
STALE_HA_THRESHOLD_HOURS = 4 # Restart HA if car data is extremely old
DOCKER_CONTAINER_NAME = "homeassistant"
CORE_SERVICE_NAME = "ev_smart_charger.service"
WEB_SERVICE_NAME = "ev_web_app.service"

def run_command(cmd_list):
    try:
        result = subprocess.run(cmd_list, capture_output=True, text=True)
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr
    except Exception as e:
        return False, str(e)

def check_core_service():
    """Checks if the core optimizer service is alive and updating its state file."""
    
    # 1. Check File Freshness
    if STATE_PATH.exists():
        # Get mtime as UTC aware datetime
        mtime_ts = STATE_PATH.stat().st_mtime
        mtime = datetime.fromtimestamp(mtime_ts, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        age = now - mtime
        
        if age > timedelta(minutes=STALE_STATE_THRESHOLD_MINUTES):
            logger.warning(f"🚨 Core Service HUNG? State file is {int(age.total_seconds()/60)} min old.")
            logger.warning(f"🔄 Restarting {CORE_SERVICE_NAME}...")
            
            success, output = run_command(["sudo", "systemctl", "restart", CORE_SERVICE_NAME])
            if success:
                logger.info("✅ Core service restarted successfully.")
            else:
                logger.error(f"❌ Failed to restart core service: {output}")
    else:
        logger.warning("⚠️ State file not found. Service might be starting up.")

def check_web_service():
    """Restarts the web dashboard if it has stopped."""
    ok, _ = run_command(["sudo", "systemctl", "is-active", "--quiet", WEB_SERVICE_NAME])
    if not ok:
        logger.warning(f"🚨 Web service down! Restarting {WEB_SERVICE_NAME}...")
        success, output = run_command(["sudo", "systemctl", "restart", WEB_SERVICE_NAME])
        if success:
            logger.info("✅ Web service restarted successfully.")
        else:
            logger.error(f"❌ Failed to restart web service: {output}")

def check_ha_health():
    """Checks if Home Assistant is providing fresh data by querying it directly."""
    config = ConfigManager.load_full_config()
    ha_conf = config['cars']['mercedes_eqv'] # Uses shared HA config
    
    if not ha_conf.get('ha_url') or not ha_conf.get('ha_token'):
        logger.warning("HA Monitor: Missing HA config, skipping health check.")
        return

    client = HomeAssistantClient(ha_conf['ha_url'], ha_conf['ha_token'])
    entity_id = ha_conf.get('ha_soc_id', 'sensor.urg48t_state_of_charge')
    
    state_obj = client.get_state(entity_id)
    if not state_obj or 'last_updated' not in state_obj:
        logger.warning(f"HA Monitor: Could not get state for {entity_id}")
        return

    last_updated_str = state_obj['last_updated']
    try:
        # HA returns ISO format with Z or +00:00
        last_updated = datetime.fromisoformat(last_updated_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        age = now - last_updated
        
        # logger.info(f"HA Health: {entity_id} age is {age}")

        if age > timedelta(hours=STALE_HA_THRESHOLD_HOURS):
            logger.warning(f"🚨 HA Data Stale! {entity_id} age: {age}")
            
            # Check if we recently restarted HA (prevent loop)
            marker_file = PROJECT_ROOT / "data" / "last_ha_restart.txt"
            can_restart = True
            if marker_file.exists():
                try:
                    last_ts = float(marker_file.read_text().strip())
                    last_restart_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc)
                    if (now - last_restart_dt) < timedelta(hours=6):
                        can_restart = False
                        logger.info("⏳ Skipping HA restart (Cooldown active).")
                except: pass
            
            if can_restart:
                logger.warning(f"🔄 Restarting Home Assistant container ({DOCKER_CONTAINER_NAME})...")
                success, output = run_command(["sudo", "docker", "restart", DOCKER_CONTAINER_NAME])
                if success:
                    logger.info("✅ Home Assistant restarted.")
                    marker_file.write_text(str(now.timestamp()))
                else:
                    logger.error(f"❌ Failed to restart HA: {output}")
    except Exception as e:
        logger.error(f"HA Monitor Error: {e}")

def main():
    logger.info("--- System Monitor Started ---")
    while True:
        try:
            check_core_service()
            check_web_service()
            check_ha_health()
        except Exception as e:
            logger.error(f"Monitor Loop Error: {e}")
        
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()