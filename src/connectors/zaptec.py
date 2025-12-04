import requests

class ZaptecCharger:
    def __init__(self, config):
        self.username = config['username']
        self.password = config['password']
        self.installation_id = config['installation_id']
        self.api_url = "https://api.zaptec.com/api"
        self.token = None
    
    def _authenticate(self):
        """
        Authenticates with Zaptec API to get a token.
        """
        # Logic to get Oauth token
        pass

    def get_status(self):
        """
        Check if a car is connected and charging.
        """
        # TODO: Real API call
        return {
            "is_charging": False,
            "power_kw": 0.0,
            "session_energy": 0.0
        }

    def start_charging(self):
        print(f"Zaptec: Sending START command to {self.installation_id}")
        # API call to start session

    def stop_charging(self):
        print(f"Zaptec: Sending STOP command to {self.installation_id}")
        # API call to stop session

    def set_charging_current(self, current_amps):
        print(f"Zaptec: Setting current to {current_amps}A")
        # API call to adjust max current
