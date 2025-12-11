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
        self.last_status = {} # Cache last status for safe command logic
    
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
        Refined to capture State IDs 710 (Mode), 510 (Power), 507 (Energy).
        """
        target_id = self.charger_id if self.charger_id else self.installation_id
        
        # Default error state
        status = {
            "operating_mode": "UNKNOWN", 
            "mode_code": -1,
            "power_kw": 0.0, 
            "energy_kwh": 0.0,
            "is_charging": False
        }

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

                # 710: Charger Operation Mode (Primary)
                # 506: Older/Alternative mode, sometimes used for stop commands
                if state_id == 710 or state_id == 506:
                    try:
                        mode_val = int(val_str)
                        status["mode_code"] = mode_val
                        if mode_val == 1: status["operating_mode"] = "DISCONNECTED"
                        elif mode_val == 2: status["operating_mode"] = "CONNECTED_WAITING"
                        elif mode_val == 3:
                            status["operating_mode"] = "CHARGING"
                            status["is_charging"] = True
                        elif mode_val == 5:
                            status["operating_mode"] = "CHARGE_DONE"
                        else:
                            status["operating_mode"] = f"UNKNOWN_MODE_{mode_val}"
                    except ValueError:
                        logger.warning(f"Zaptec: Invalid Operating Mode value: {val_str}")

                elif state_id == 510: # Total Power (W)
                    try:
                        power_kw = float(val_str) / 1000.0
                        status["power_kw"] = power_kw
                        # Secondary check: if power is significant, we are charging
                        if power_kw > 0.1:
                            status["is_charging"] = True
                    except ValueError:
                        logger.warning(f"Zaptec: Invalid Power value: {val_str}")
                
                elif state_id == 507: # Session Energy (kWh)
                    try:
                         status["energy_kwh"] = float(val_str)
                    except ValueError:
                        pass

            self.last_status = status
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
        """
        Sends Start command (501). 
        Checks status first to avoid redundant calls.
        """
        target_id = self.charger_id if self.charger_id else self.installation_id
        
        # 1. Check current status
        current_status = self.get_status()
        if current_status["is_charging"] or current_status["mode_code"] == 3:
            logger.info(f"Zaptec: Already charging (Mode {current_status['mode_code']}). Skipping START command.")
            return True

        if current_status["mode_code"] == 1:
            logger.warning("Zaptec: Cannot start charging - Car is DISCONNECTED (Mode 1).")
            # We don't return False here necessarily, as plugging in might happen any second, 
            # but usually we shouldn't try.
            return False

        logger.info(f"Zaptec: Sending START command to {target_id}")
        if self._send_command(501):
            logger.info(f"Zaptec: START command sent successfully to {target_id}")
            return True
        else:
            logger.error(f"Zaptec: Failed to send START command to {target_id}")
            return False

    def stop_charging(self, aggressive=False):
        """
        Sends Stop command (502).
        Checks status first to avoid redundant calls which cause "Stopped too many times" errors.

        Args:
            aggressive (bool): If True, sends multiple STOP commands to override persistent car requests
        """
        target_id = self.charger_id if self.charger_id else self.installation_id

        # 1. Check current status
        current_status = self.get_status()

        # Modes where we are effectively already stopped:
        # 1: Disconnected
        # 2: Connected Waiting (Paused)
        # 5: Charge Done
        safe_stop_modes = [1, 2, 5]

        if current_status["mode_code"] in safe_stop_modes and not current_status["is_charging"]:
            logger.info(f"Zaptec: Already stopped/waiting (Mode {current_status['mode_code']}). Skipping STOP command.")
            return True

        if not aggressive:
            # Normal stop - single command
            logger.info(f"Zaptec: Sending STOP command to {target_id}")
            if self._send_command(502):
                logger.info(f"Zaptec: STOP command sent successfully to {target_id}")
                return True
            else:
                logger.error(f"Zaptec: Failed to send STOP command to {target_id}")
                return False
        else:
            # Aggressive stop - send command 3 times with 2 second intervals
            # This helps override persistent charging requests from the car
            import time
            logger.info(f"Zaptec: Sending AGGRESSIVE STOP to {target_id} (3x commands)")
            success_count = 0

            for attempt in range(3):
                if self._send_command(502):
                    success_count += 1
                    logger.info(f"Zaptec: Aggressive STOP attempt {attempt + 1}/3 successful")
                    if attempt < 2:  # Don't sleep after last attempt
                        time.sleep(2)
                else:
                    logger.warning(f"Zaptec: Aggressive STOP attempt {attempt + 1}/3 failed")

            if success_count > 0:
                logger.info(f"Zaptec: Aggressive STOP completed ({success_count}/3 commands successful)")
                return True
            else:
                logger.error(f"Zaptec: All aggressive STOP attempts failed")
                return False

    def set_charging_current(self, current_amps):
        """
        Sets the available current for the installation (Load Balancing).
        Target: /api/installation/{id}/update
        """
        if not self.installation_id:
             logger.error("Zaptec: Cannot set current - No installation_id configured.")
             return False

        headers = self._get_headers()
        if not headers:
             return False

        url = f"{self.api_url}/installation/{self.installation_id}/update"
        payload = {
            "AvailableCurrent": int(current_amps)
        }
        
        logger.info(f"Zaptec: Setting installation current to {current_amps}A")
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            logger.info(f"Zaptec: Current set to {current_amps}A successfully.")
            return True
        except requests.exceptions.HTTPError as e:
            logger.error(f"Zaptec Set Current Error: {e.response.status_code} - {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Zaptec Set Current Exception: {e}")
            return False

    def restart_charger(self):
        """
        Sends Restart command (102) to the charger.
        """
        target_id = self.charger_id if self.charger_id else self.installation_id
        logger.info(f"Zaptec: Sending RESTART command (102) to {target_id}")
        if self._send_command(102):
            logger.info(f"Zaptec: RESTART command sent successfully to {target_id}")
            return True
        else:
            logger.error(f"Zaptec: Failed to send RESTART command to {target_id}")
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
