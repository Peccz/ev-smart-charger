import requests
import json
import time

class ZaptecCharger:
    def __init__(self, config):
        self.username = config['username']
        self.password = config['password']
        self.installation_id = config['installation_id']
        self.api_url = "https://api.zaptec.com/api"
        self.token = None
        self.token_expires = 0
    
    def _authenticate(self):
        """
        Authenticates with Zaptec API using User/Pass to get OAuth token.
        """
        if self.token and time.time() < self.token_expires:
            return

        url = "https://api.zaptec.com/oauth/token"
        payload = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password
        }
        
        try:
            response = requests.post(url, data=payload)
            response.raise_for_status()
            data = response.json()
            self.token = data['access_token']
            self.token_expires = time.time() + data['expires_in'] - 60 # Buffer
        except Exception as e:
            print(f"Zaptec Auth Error: {e}")
            self.token = None

    def _get_headers(self):
        self._authenticate()
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def get_status(self):
        """
        Check if a car is connected and charging via the Installation state.
        """
        if not self.installation_id:
            return {"is_charging": False, "power_kw": 0.0}

        # Endpoint for installation state
        url = f"{self.api_url}/chargers/{self.installation_id}/state"
        
        try:
            response = requests.get(url, headers=self._get_headers())
            response.raise_for_status()
            data = response.json()
            
            # Observation ID 506 is "Operating Mode" (1=Disconnected, 2=Connected, 3=Charging)
            # Observation ID 507 is "Active Power Phase 1" etc...
            # But easier is usually to look at 'Power' if available, or interpret mode.
            
            # Simplify: Find operating mode
            is_charging = False
            power = 0.0
            
            # Depending on API version, data structure varies. 
            # Typically data is list of observations.
            # We will assume basic API response structure here.
            
            # Note: For Zaptec Go, we might need to query the specific charger ID, not installation ID 
            # if there are multiple. Assuming installation_id IS the charger ID for home use.
            
            # Example logic:
            for obs in data:
                if obs['stateId'] == 506: # Operating Mode
                    mode = int(obs['valueAsString'])
                    if mode == 3: # Charging
                        is_charging = True
                if obs['stateId'] == 510: # Total Power (W)
                    power = float(obs['valueAsString']) / 1000.0 # to kW

            return {
                "is_charging": is_charging,
                "power_kw": power,
                "session_energy": 0.0 # Need separate call for session details usually
            }

        except Exception as e:
            print(f"Zaptec Status Error: {e}")
            return {"is_charging": False, "power_kw": 0.0}

    def start_charging(self):
        print(f"Zaptec: Sending START command to {self.installation_id}")
        self._send_command(501) # 501 = Start Charging

    def stop_charging(self):
        print(f"Zaptec: Sending STOP command to {self.installation_id}")
        self._send_command(502) # 502 = Stop Charging

    def _send_command(self, command_id):
        url = f"{self.api_url}/chargers/{self.installation_id}/sendCommand"
        payload = {
            "commandId": command_id
        }
        try:
            requests.post(url, json=payload, headers=self._get_headers())
        except Exception as e:
            print(f"Zaptec Command Error: {e}")