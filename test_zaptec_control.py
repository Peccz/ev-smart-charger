import logging
import sys
import os
import time

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure src is in path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from config_manager import ConfigManager
from connectors.zaptec import ZaptecCharger

def test_control():
    logger.info("--- ZAPTEC CONTROL TEST ---")
    
    # 1. Load Config
    config = ConfigManager.load_full_config()
    zap_config = config.get('charger', {}).get('zaptec', {})
    
    if not zap_config.get('username'):
        logger.error("No Zaptec credentials found!")
        return

    charger = ZaptecCharger(zap_config)
    
    # 2. Check Initial Status
    logger.info("Checking initial status...")
    status = charger.get_status()
    logger.info(f"Initial Status: {status}")
    
    if status.get('operating_mode') == 'DISCONNECTED':
        logger.warning("⚠️ No car connected! Commands might be ignored by charger.")
    
    # 3. Send START Command
    logger.info("🚀 Sending START command (501)...")
    success = charger.start_charging()
    if success:
        logger.info("✅ Start command sent successfully.")
    else:
        logger.error("❌ Failed to send Start command.")
        
    # 4. Wait and Check
    logger.info("Waiting 10 seconds...")
    time.sleep(10)
    status = charger.get_status()
    logger.info(f"Status after Start: {status}")

    # 5. Send STOP Command
    logger.info("🛑 Sending STOP command (502)...")
    success = charger.stop_charging()
    if success:
        logger.info("✅ Stop command sent successfully.")
    else:
        logger.error("❌ Failed to send Stop command.")

    # 6. Final Check
    logger.info("Waiting 5 seconds...")
    time.sleep(5)
    status = charger.get_status()
    logger.info(f"Final Status: {status}")

if __name__ == "__main__":
    test_control()
