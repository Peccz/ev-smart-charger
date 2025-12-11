# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EV Smart Charger is a Python-based intelligent charging system for electric vehicles (Mercedes EQV and Nissan Leaf) that optimizes charging based on electricity spot prices, weather forecasts, and user preferences. The system controls a Zaptec Go charger and integrates with Home Assistant for vehicle telemetry.

## Development Commands

### Running the System Locally

```bash
# Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run optimizer manually (single cycle)
./venv/bin/python src/main.py

# Run web dashboard
./venv/bin/python src/web_app.py
# Access at http://localhost:5000
```

### Production Commands (on Raspberry Pi)

```bash
# View service status
sudo systemctl status ev_smart_charger.service
sudo systemctl status ev_web_app.service
sudo systemctl status monitor.service

# Restart services
sudo systemctl restart ev_smart_charger.service ev_web_app.service monitor.service

# View logs (real-time)
sudo journalctl -u ev_smart_charger.service -f
sudo journalctl -u ev_web_app.service -f

# View recent logs
sudo journalctl -u ev_smart_charger.service -n 100
```

### Database Inspection

```bash
# Check vehicle status
sqlite3 data/ev_charger.db "SELECT * FROM vehicle_log ORDER BY timestamp DESC LIMIT 10"

# Check charging sessions
sqlite3 data/ev_charger.db "SELECT * FROM charging_sessions ORDER BY start_time DESC LIMIT 5"

# Check system metrics
sqlite3 data/ev_charger.db "SELECT * FROM system_metrics ORDER BY timestamp DESC LIMIT 10"
```

### Deployment

```bash
# From development machine, deploy to RPi
./deploy_generic.sh
```

This script automatically commits, pushes to GitHub, pulls on RPi, and restarts services. **Note:** `data/secrets.json` is not copied for security.

## Architecture

### Core Components

1. **Optimizer Loop (`src/main.py`)**
   - Runs every minute via systemd timer
   - Fetches spot prices, weather, vehicle status
   - Determines active vehicle via "Charging Detective" logic
   - Calculates optimal charging schedule
   - Controls Zaptec charger via API
   - Logs all data to SQLite database

2. **Web Dashboard (`src/web_app.py`)**
   - Flask app on port 5000
   - Real-time vehicle status display
   - Manual override controls ("Ladda Nu", "Stop", "Auto")
   - SoC target configuration
   - Historical graphs and planning view

3. **Optimization Engine (`src/optimizer/engine.py`)**
   - Dynamic target SoC calculation based on price trends
   - Cheapest-hours scheduling with deadline awareness
   - Storm buffering logic (low wind + low temp = charge to 95%)
   - Price forecasting with diurnal profiles, wind, solar, and temperature factors

4. **Vehicle Connectors (`src/connectors/vehicles.py`)**
   - **Mercedes EQV**: Home Assistant integration
   - **Nissan Leaf**: Home Assistant integration with auto-wake feature
   - Both use `HomeAssistantClient` for state queries and service calls

5. **Charger Control (`src/connectors/zaptec.py`)**
   - Zaptec API integration for start/stop charging
   - OAuth token management with automatic refresh
   - Real-time power and energy monitoring

6. **External Data Sources**
   - **Spot Prices** (`src/connectors/spot_price.py`): Fetches from elprisetjustnu.se API
   - **Weather** (`src/connectors/weather.py`): Open-Meteo API for forecasts

### Configuration System

The system uses **absolute paths** throughout via `config_manager.PROJECT_ROOT`. This ensures services work regardless of working directory.

#### Configuration Files

1. **`config/settings.yaml`** - Base configuration (vehicles, location, grid region)
2. **`data/secrets.json`** - API credentials (NOT in Git)
   ```json
   {
     "home_assistant": {"url": "...", "token": "..."},
     "zaptec": {"username": "...", "password": "...", "charger_id": "..."},
     "nissan": {"vin": "...", "username": "...", "password": "..."}
   }
   ```
3. **`data/user_settings.json`** - User preferences (updated via web GUI)
4. **`data/manual_overrides.json`** - Temporary manual control states
5. **`data/optimizer_state.json`** - Last optimizer decisions (for UI display)

#### Sensor Configuration

Home Assistant sensor entity IDs are **hardcoded** in `src/config_manager.py` under `HARDCODED_SENSORS` for reliability. This ensures the system always uses the correct entities regardless of user configuration.

**Mercedes EQV Sensors:**
- SoC: `sensor.urg48t_state_of_charge`
- Plugged: `sensor.urg48t_range_electric` (logic based on `chargingstatus` attribute)
- Range: `sensor.urg48t_range_electric`
- Odometer: `sensor.urg48t_odometer`

**Nissan Leaf Sensors:**
- SoC: `sensor.leaf_battery_level`
- Plugged: `binary_sensor.leaf_plugged_in`
- Range: `sensor.leaf_range_ac_on`
- Last Updated: `sensor.leaf_last_updated`
- Odometer: `sensor.leaf_odometer`
- Update Button: `button.leaf_update_data`

### Optimization Logic

The optimizer implements a sophisticated multi-factor strategy:

1. **Dynamic Target SoC**:
   - Compares short-term (12h) vs long-term average prices
   - If short-term < 90% of long-term: charge to max_soc (aggressive)
   - If short-term > 110% of long-term: charge to min_soc (conservative)
   - Otherwise: linear interpolation (balanced)

2. **Deadline-Aware Scheduling**:
   - User sets departure time (default 07:00)
   - Optimizer selects N cheapest hours before deadline (N = hours needed)
   - If not enough time: enters "Panic Mode" and charges immediately

3. **Manual Overrides**:
   - Web GUI can set CHARGE or STOP overrides with expiry
   - Overrides always take precedence over optimization logic
   - Stored in `data/manual_overrides.json`

4. **Storm Buffering**:
   - If avg wind < 8 km/h AND temp < -2°C: override target to 95%
   - Predicts price spikes during low wind + high demand

5. **Price Forecasting**:
   - Extends official prices with ML-lite model
   - Factors: diurnal cycles (weekday/weekend profiles), wind speed, solar radiation, temperature, seasonality
   - Generates 3-day forecasts saved to `data/forecast_history.json`

### Charging Detective

When the Zaptec charger reports active charging, the system determines which vehicle is being charged:

```python
if charger.is_charging:
    if mercedes_plugged and not leaf_plugged: active = "mercedes_eqv"
    elif leaf_plugged and not mercedes_plugged: active = "nissan_leaf"
    elif both_plugged: active = "UNKNOWN_BOTH"
    else: active = "UNKNOWN_NONE"
```

This information is logged to `system_metrics` table for analytics.

### Nissan Leaf Auto-Wake Feature

The Nissan Leaf connector includes automatic wake-up logic:
- Checks `sensor.leaf_last_updated` for data staleness
- If data > 4 hours old: triggers `button.leaf_update_data`
- Cooldown period: 60 minutes between wake attempts
- Implementation: `src/connectors/vehicles.py:239-256`

## Key Patterns

### 1. Absolute Paths Everywhere

**Never use relative paths.** All file operations use absolute paths from `config_manager`:

```python
from config_manager import SETTINGS_PATH, DATABASE_PATH, PROJECT_ROOT

# Good
with open(SETTINGS_PATH, 'r') as f:
    settings = json.load(f)

# Bad (will break in systemd context)
with open('data/user_settings.json', 'r') as f:
    settings = json.load(f)
```

### 2. Config Loading Hierarchy

`ConfigManager.load_full_config()` merges configs in this order:
1. Load `config/settings.yaml`
2. Merge `data/secrets.json`
3. Merge `data/user_settings.json`
4. **Override with hardcoded sensors** (for reliability)

### 3. Error Handling Philosophy

The optimizer is **fail-safe by default**:
- If price data unavailable: charge immediately (safety over cost)
- If vehicle status fails: log error and continue with other vehicles
- If charger control fails: log error but don't crash

### 4. Service Communication

Services communicate via JSON files:
- `main.py` writes to `optimizer_state.json`
- `web_app.py` reads state files and writes to `manual_overrides.json`
- `monitor_changes.py` watches Home Assistant and updates `manual_status.json`

## Common Tasks

### Adding a New Vehicle Connector

1. Subclass `Vehicle` in `src/connectors/base.py`
2. Implement `get_status()` returning `{"soc": int, "range_km": int, "plugged_in": bool, "odometer": int, "climate_active": bool}`
3. Add config section to `config/settings.yaml`
4. Add sensor IDs to `HARDCODED_SENSORS` in `config_manager.py`
5. Update merge logic in `ConfigManager.load_full_config()`
6. Add vehicle instantiation in `src/main.py`

### Modifying Optimization Logic

The core logic is in `src/optimizer/engine.py`:
- `suggest_action()`: Main decision function
- `_calculate_dynamic_target()`: Target SoC calculation
- `_generate_price_forecast()`: Price forecasting model
- `calculate_urgency()`: Hours-needed calculation

**Always test locally first:**
```bash
./venv/bin/python src/main.py  # Single run to verify logic
```

### Adding Web Dashboard Features

1. Add route in `src/web_app.py`
2. Add template in `src/web/templates/`
3. Add static assets in `src/web/static/`
4. Restart web service: `sudo systemctl restart ev_web_app.service`

### Debugging Production Issues

```bash
# 1. Check service status
systemctl status ev_smart_charger.service

# 2. View recent errors
sudo journalctl -u ev_smart_charger.service --since "1 hour ago" | grep -i error

# 3. Test components manually via SSH
ssh peccz@100.100.118.62
cd /home/peccz/ev_smart_charger
./venv/bin/python << 'EOF'
import sys
sys.path.insert(0, "src")
from config_manager import ConfigManager
from connectors.vehicles import NissanLeaf

config = ConfigManager.load_full_config()
leaf = NissanLeaf(config['cars']['nissan_leaf'])
status = leaf.get_status()
print(status)
EOF
```

## Testing

### Manual Charging Test

Via web GUI: http://100.100.118.62:5000
1. Click "⚡ Ladda Nu" → Creates 60-minute CHARGE override
2. Wait 1 minute for optimizer cycle
3. Verify charger starts via Zaptec app or web dashboard

Via curl:
```bash
curl -X POST http://100.100.118.62:5000/api/charge_now \
  -H "Content-Type: application/json" \
  -d '{"vehicle_id": "nissan_leaf"}'
```

### Price Forecasting Test

```bash
cd /home/peccz/ev_smart_charger
./venv/bin/python debug_prices.py
# Check data/forecast_history.json for generated forecasts
```

## Important Notes

- **Security**: Never commit `data/secrets.json` or any files containing API credentials
- **Database**: The SQLite database at `data/ev_charger.db` grows over time. Monitor disk usage on RPi.
- **Home Assistant Token**: Long-lived access tokens must be regenerated if expired (create in HA Profile)
- **Zaptec API**: Uses OAuth with automatic token refresh. Tokens stored in memory only.
- **Time Zones**: All times use Europe/Stockholm timezone. Database uses ISO format with timezone info.
- **Web Dashboard Port**: Runs on port 5000 (not 80/443). Access via `http://100.100.118.62:5000`

## Related Documentation

- `README.md` - User guide with installation, troubleshooting, and operations
- `DEPLOY_INSTRUCTIONS.md` - Detailed deployment procedures
- `HOMEASSISTANT_SETUP.md` - Home Assistant integration guide
- `ZAPTEC_SETUP.md` - Zaptec charger configuration
