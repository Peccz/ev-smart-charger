import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

class ChargerGuard:
    def __init__(self, state_file_path):
        self.state_file = Path(state_file_path)
        self.cooldown_minutes = 10
        self.validation_minutes = 5
        self.lockout_minutes = 60
        self.max_daily_restarts = 5
        
        self.state = self._load_state()

    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"ChargerGuard: Error loading state: {e}")
        
        return {
            "last_command": "STOP",
            "last_command_time": "1970-01-01T00:00:00",
            "last_successful_charge_time": "1970-01-01T00:00:00",
            "failure_mode_until": "1970-01-01T00:00:00",
            "daily_restarts": 0,
            "last_restart_date": ""
        }

    def _save_state(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"ChargerGuard: Error saving state: {e}")

    def can_execute(self, action):
        now = datetime.now()
        last_time = datetime.fromisoformat(self.state["last_command_time"])
        
        # 1. Failure Mode Check
        lockout_until = datetime.fromisoformat(self.state["failure_mode_until"])
        if action == "START" and now < lockout_until:
            logger.warning(f"ChargerGuard: Lockout active until {lockout_until.strftime('%H:%M')}")
            return False, f"Lockout active until {lockout_until.strftime('%H:%M')}"

        # 2. Cooldown Check (Between any commands)
        if (now - last_time) < timedelta(minutes=self.cooldown_minutes):
            if action != self.state["last_command"]:
                remaining = int((timedelta(minutes=self.cooldown_minutes) - (now - last_time)).total_seconds() / 60)
                logger.warning(f"ChargerGuard: Cooldown active. {remaining} min left.")
                return False, f"Cooldown: {remaining} min kvar"

        # 3. Daily Restart Check
        today = now.strftime("%Y-%m-%d")
        if self.state["last_restart_date"] != today:
            self.state["daily_restarts"] = 0
            self.state["last_restart_date"] = today

        if action == "START" and self.state["daily_restarts"] >= self.max_daily_restarts:
            logger.error("ChargerGuard: Max daily restarts reached. Manual intervention required.")
            return False, "Max antal omstarter per dag uppnått"

        return True, "OK"

    def register_command(self, action):
        now = datetime.now()
        if action == "START" and self.state["last_command"] == "STOP":
            self.state["daily_restarts"] += 1
            
        self.state["last_command"] = action
        self.state["last_command_time"] = now.isoformat()
        self._save_state()

    def validate_power(self, is_charging, current_power_kw):
        """
        Checks if a START command actually resulted in power flow.
        If not, triggers failure mode.
        """
        if self.state["last_command"] != "START":
            return True

        now = datetime.now()
        cmd_time = datetime.fromisoformat(self.state["last_command_time"])
        
        # Wait a few minutes before validating
        if (now - cmd_time) > timedelta(minutes=self.validation_minutes):
            if not is_charging or current_power_kw < 0.1:
                logger.error(f"ChargerGuard: Dead-start detected! Power: {current_power_kw}kW. Triggering Lockout.")
                self.trigger_lockout()
                return False
            else:
                self.state["last_successful_charge_time"] = now.isoformat()
                self._save_state()
        
        return True

    def trigger_lockout(self, minutes=None):
        if minutes is None:
            minutes = self.lockout_minutes
        self.state["failure_mode_until"] = (datetime.now() + timedelta(minutes=minutes)).isoformat()
        self._save_state()
