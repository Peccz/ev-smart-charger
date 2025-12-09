import requests
import json
import time
import logging
from .base import Charger

logger = logging.getLogger(__name__)

class ZaptecCharger(Charger):
    def __init__(self, config):
        super().__init__(config)
        self.username = config.get('username')
        self.password = config.get('password')
        self.installation_id = config.get('installation_id')
        self.charger_id = config.get('charger_id')
        self.api_url = "https://api.zaptec.com/api"
        self.token = None
        self.token_expires = 0
    
    def validate_config(self):
        if not self.config.get('username') or not self.config.get('password'):
            logger.error("Zaptec: Username and password are required.")
        if not self.config.get('installation_id') and not self.config.get('charger_id'):
            logger.error("Zaptec: Either installation_id or charger_id is required.")

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
            response = requests.post(url, data=payload, timeout=10)
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
            "User-Agent": "EV-SmartCharger/1.0 (+https://github.com/Peccz/ev-smart-charger)"
        }

    def get_status(self):
        """
        Check if a car is connected and charging via the Installation state.
        """
        target_id = self.charger_id if self.charger_id else self.installation_id
        
        # Default error state
        status = {"operating_mode": "UNKNOWN", "power_kw": 0.0, "is_charging": False}

        if not target_id:
            return status
        
        headers = self._get_headers()
        if not headers:
            status["operating_mode"] = "AUTH_FAILED"
            return status

        url = f"{self.api_url}/chargers/{target_id}/state"
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            for obs in data:
                # Handle case-sensitivity in API response (StateId vs stateId)
                state_id = obs.get('StateId', obs.get('stateId'))
                val_str = obs.get('ValueAsString', obs.get('valueAsString', '0'))

                # Check both StateId 506 and 710 for Operating Mode
                # 710 is "Charger Operation Mode" and more reliable
                if state_id == 506 or state_id == 710: # Operating Mode
                    try:
                        mode_val = int(val_str)
                        if mode_val == 1: status["operating_mode"] = "DISCONNECTED"
                        elif mode_val == 2: status["operating_mode"] = "CONNECTED_WAITING"
                        elif mode_val == 3:
                            status["operating_mode"] = "CHARGING"
                            status["is_charging"] = True
                        elif mode_val == 5:
                            status["operating_mode"] = "CHARGE_DONE"
                    except ValueError:
                        logger.warning(f"Zaptec: Invalid Operating Mode value: {val_str}")

                elif state_id == 510: # Total Power (W)
                    try:
                        power_kw = float(val_str) / 1000.0
                        status["power_kw"] = power_kw
                        # Also set is_charging if power is significant (>0.5 kW)
                        if power_kw > 0.5:
                            status["is_charging"] = True
                    except ValueError:
                        logger.warning(f"Zaptec: Invalid Power value: {val_str}")

            return status

        except requests.exceptions.HTTPError as e:
            logger.error(f"Zaptec Status HTTP Error ({target_id}): {e.response.status_code} - {e.response.text}")
            status["operating_mode"] = "API_ERROR"
            return status
        except Exception as e:
            logger.error(f"Zaptec Status Error ({target_id}): {e}")
            status["operating_mode"] = "ERROR"
            return status

    def start_charging(self):
        target_id = self.charger_id if self.charger_id else self.installation_id
        logger.info(f"Zaptec: Sending START command to {target_id}")
        if self._send_command(501):
            logger.info(f"Zaptec: START command sent successfully to {target_id}")
            return True
        else:
            logger.error(f"Zaptec: Failed to send START command to {target_id}")
            return False

    def stop_charging(self):
        target_id = self.charger_id if self.charger_id else self.installation_id
        logger.info(f"Zaptec: Sending STOP command to {target_id}")
        if self._send_command(502):
            logger.info(f"Zaptec: STOP command sent successfully to {target_id}")
            return True
        else:
            logger.error(f"Zaptec: Failed to send STOP command to {target_id}")
            return False

    def _send_command(self, command_id, max_retries=3):
        """
        Send command to Zaptec charger with exponential backoff on 5xx errors.

        Args:
            command_id: Zaptec command ID (501=start, 502=stop)
            max_retries: Maximum number of retry attempts

        Returns:
            bool: True if successful, False otherwise
        """
        target_id = self.charger_id if self.charger_id else self.installation_id
        headers = self._get_headers()
        if not headers:
            logger.error("Zaptec: Failed to get API headers for command, authentication failed.")
            return False

        url = f"{self.api_url}/chargers/{target_id}/sendCommand/{command_id}"
        payload = {}

        for attempt in range(max_retries):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=10)
                response.raise_for_status()
                logger.info(f"Zaptec: Command {command_id} successful on attempt {attempt + 1}")
                return True

            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code

                # Retry on 5xx server errors with exponential backoff
                if status_code >= 500 and attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(f"Zaptec: Command HTTP {status_code} (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    # Don't retry on 4xx client errors or after max retries
                    logger.error(f"Zaptec Command HTTP Error ({command_id}, {target_id}): {status_code} - {e.response.text}")
                    return False

            except Exception as e:
                logger.error(f"Zaptec Command Error ({command_id}, {target_id}): {e}")
                return False

        return False
