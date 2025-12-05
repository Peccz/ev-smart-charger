import requests
import json
import time
import logging

logger = logging.getLogger(__name__)

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
            return True # Token is still valid

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
            logger.info("Zaptec: Successfully authenticated and obtained new token.")
            return True
        except requests.exceptions.HTTPError as e:
            logger.error(f"Zaptec Auth HTTP Error: {e.response.status_code} - {e.response.text}")
            self.token = None
            return False
        except Exception as e:
            logger.error(f"Zaptec Auth Error: {e}")
            self.token = None
            return False

    def _get_headers(self):
        if not self._authenticate(): # Ensure token is fresh before getting headers
            return None
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "EV-SmartCharger/1.0 (+https://github.com/Peccz/ev-smart-charger)" # Custom User-Agent
        }

    def get_status(self):
        """
        Check if a car is connected and charging via the Installation state.
        """
        if not self.installation_id:
            logger.warning("Zaptec: Installation ID is not configured.")
            return {"operating_mode": "UNKNOWN", "power_kw": 0.0, "is_charging": False}
        
        headers = self._get_headers()
        if not headers:
            logger.error("Zaptec: Failed to get API headers, authentication failed.")
            return {"operating_mode": "AUTH_FAILED", "power_kw": 0.0, "is_charging": False}

        url = f"{self.api_url}/chargers/{self.installation_id}/state"
        
        try:
            response = requests.get(url, headers=headers)
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
            logger.error(f"Zaptec Status HTTP Error ({self.installation_id}): {e.response.status_code} - {e.response.text}")
            return {"operating_mode": "API_ERROR", "power_kw": 0.0, "is_charging": False}
        except Exception as e:
            logger.error(f"Zaptec Status Error ({self.installation_id}): {e}")
            return {"is_charging": False, "power_kw": 0.0}

    def start_charging(self):
        logger.info(f"Zaptec: Sending START command to {self.installation_id}")
        if self._send_command(501):
            logger.info(f"Zaptec: START command sent successfully to {self.installation_id}")
            return True
        else:
            logger.error(f"Zaptec: Failed to send START command to {self.installation_id}")
            return False

    def stop_charging(self):
        logger.info(f"Zaptec: Sending STOP command to {self.installation_id}")
        if self._send_command(502):
            logger.info(f"Zaptec: STOP command sent successfully to {self.installation_id}")
            return True
        else:
            logger.error(f"Zaptec: Failed to send STOP command to {self.installation_id}")
            return False

    def _send_command(self, command_id):
        headers = self._get_headers()
        if not headers:
            logger.error("Zaptec: Failed to get API headers for command, authentication failed.")
            return False

        url = f"{self.api_url}/chargers/{self.installation_id}/sendCommand"
        payload = {
            "commandId": command_id
        }
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return True
        except requests.exceptions.HTTPError as e:
            logger.error(f"Zaptec Command HTTP Error ({command_id}, {self.installation_id}): {e.response.status_code} - {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Zaptec Command Error ({command_id}, {self.installation_id}): {e}")
            return False