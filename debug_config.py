from src.config_manager import ConfigManager
import json

c = ConfigManager.load_full_config()
print(json.dumps(c['cars'], indent=2))
