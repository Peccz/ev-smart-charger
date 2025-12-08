import logging
import sys
import os

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure src is in path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from config_manager import ConfigManager
from connectors.zaptec import ZaptecCharger
from connectors.vehicles import MercedesEQV, NissanLeaf

def mask_secret(secret):
    if not secret or len(secret) < 8:
        return "****"
    return secret[:4] + "****" + secret[-4:]

def test_config_loading():
    logger.info("--- Testing Config Loading ---")
    config = ConfigManager.load_full_config()
    
    # Check Zaptec
    zap = config.get('charger', {}).get('zaptec', {})
    logger.info(f"Zaptec Username: {zap.get('username')}")
    logger.info(f"Zaptec Password: {mask_secret(zap.get('password'))}")
    logger.info(f"Zaptec Charger ID: {zap.get('charger_id')}")
    
    # Check HA
    merc = config.get('cars', {}).get('mercedes_eqv', {})
    logger.info(f"Mercedes HA URL: {merc.get('ha_url')}")
    logger.info(f"Mercedes HA Token: {mask_secret(merc.get('ha_token'))}")
    
    return config

def test_zaptec(config):
    logger.info("\n--- Testing Zaptec Connection ---")
    zap_config = config.get('charger', {}).get('zaptec', {})
    if not zap_config.get('username'):
        logger.warning("Skipping Zaptec test (no credentials)")
        return

    try:
        zap = ZaptecCharger(zap_config)
        status = zap.get_status()
        logger.info(f"Zaptec Status: {status}")
    except Exception as e:
        logger.error(f"Zaptec Connection Failed: {e}")

def test_mercedes(config):
    logger.info("\n--- Testing Mercedes Connection (via HA) ---")
    merc_config = config.get('cars', {}).get('mercedes_eqv', {})
    if not merc_config.get('ha_token'):
        logger.warning("Skipping Mercedes test (no HA token)")
        return

    try:
        car = MercedesEQV(merc_config)
        status = car.get_status()
        logger.info(f"Mercedes Status: {status}")
    except Exception as e:
        logger.error(f"Mercedes Connection Failed: {e}")

def test_nissan(config):
    logger.info("\n--- Testing Nissan Connection (via HA) ---")
    nis_config = config.get('cars', {}).get('nissan_leaf', {})
    if not nis_config.get('ha_token'):
        logger.warning("Skipping Nissan test (no HA token)")
        return

    try:
        car = NissanLeaf(nis_config)
        status = car.get_status()
        logger.info(f"Nissan Status: {status}")
    except Exception as e:
        logger.error(f"Nissan Connection Failed: {e}")

if __name__ == "__main__":
    try:
        full_config = test_config_loading()
        test_zaptec(full_config)
        test_mercedes(full_config)
        test_nissan(full_config)
    except Exception as e:
        logger.error(f"Test Suite Failed: {e}")
