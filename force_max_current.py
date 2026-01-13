from src.connectors.zaptec import ZaptecCharger
from src.config_manager import ConfigManager

def force_current():
    config = ConfigManager.load_full_config()
    zaptec_config = config['charger']['zaptec']
    charger = ZaptecCharger(zaptec_config)
    
    print("Forcing Zaptec Installation Current to 16A...")
    if charger.set_charging_current(16):
        print("Success! Check charging power.")
    else:
        print("Failed to set current.")

if __name__ == "__main__":
    force_current()
