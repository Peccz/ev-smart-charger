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
from connectors.vehicles import NissanLeaf

def test_wakeup():
    logger.info("--- NISSAN WAKEUP TEST ---")
    
    config = ConfigManager.load_full_config()
    nis_config = config.get('cars', {}).get('nissan_leaf', {})
    
    if not nis_config.get('ha_token'):
        logger.error("No HA token found for Nissan.")
        return

    nissan = NissanLeaf(nis_config)
    
    logger.info("Sending wake_up command...")
    success = nissan.wake_up()
    
    if success:
        logger.info("✅ Wake up command sent successfully via HA!")
        logger.info("Check HA or Nissan app to see if it updates.")
    else:
        logger.error("❌ Failed to send wake up command.")

if __name__ == "__main__":
    test_wakeup()
