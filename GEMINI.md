# EV Smart Charger Project

## Workspace Overview

This workspace contains a Python-based EV Smart Charger project designed to optimize electric vehicle charging based on spot prices, weather forecasts, and user preferences. It consists of a core optimization engine, various connectors for external services (vehicles, charger, spot price, weather), a web-based dashboard for monitoring and control, and `systemd` services for deployment.

### Project Structure

The project is organized as follows:

*   `ev_smart_charger.service`: `systemd` service file for the main optimization script.
*   `ev_web_app.service`: `systemd` service file for the web application dashboard.
*   `requirements.txt`: Python dependencies.
*   `setup_mercedes.py`: Script for Mercedes Me authentication setup.
*   `config/`:
    *   `settings.template.yaml`: Template for the main application configuration.
*   `data/`: Directory for dynamic data, including `user_settings.json`, `manual_overrides.json`, `optimizer_state.json`, and `manual_status.json`.
*   `src/`: Contains the core Python source code.
    *   `main.py`: The main entry point for the optimization engine.
    *   `web_app.py`: The Flask web application for the dashboard.
    *   `connectors/`: Modules for integrating with external services (e.g., `spot_price.py`, `weather.py`, `vehicles.py`, `zaptec.py`, `mercedes_api/token_client.py`).
    *   `database/`: Database management module (`db_manager.py`).
    *   `optimizer/`: The charging optimization engine (`engine.py`).
    *   `web/`: Web application assets.
        *   `static/`: CSS and JS files.
        *   `templates/`: HTML templates (`index.html`, `planning.html`, `settings.html`).

## Project Overview

The EV Smart Charger project aims to intelligently charge electric vehicles to minimize cost and ensure readiness.

*   **Core Logic (`src/main.py`):** Runs hourly to fetch data (spot prices, weather, vehicle status), calculate optimal charging schedules, and control the Zaptec charger. It uses a configuration defined in `config/settings.yaml` and user preferences from `data/user_settings.json`.
*   **Web Dashboard (`src/web_app.py`):** A Flask application providing a user interface to view vehicle status, charging plans, adjust settings, and set manual overrides.
*   **Connectors:** Integrates with various APIs:
    *   **Vehicles:** Mercedes Me (for EQV) and Nissan Connect (for Leaf).
    *   **Charger:** Zaptec charger control.
    *   **External Data:** Spot price data and weather forecasts.
*   **Configuration:** Uses `YAML` files for static configuration and `JSON` files for dynamic user settings and operational state.
*   **Deployment:** Designed to run as `systemd` services on a Raspberry Pi, managed by the `deploy.sh` script.

## Building and Running

### 1. Install Dependencies

It is recommended to use a virtual environment.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configuration

Create your `config/settings.yaml` file by copying and filling out `config/settings.template.yaml`. This file contains static configuration like location, grid provider, and car capacities.

```bash
cp config/settings.template.yaml config/settings.yaml
# Edit config/settings.yaml with your specific details
```

### 3. Mercedes Me Authentication

If you are using a Mercedes vehicle, you need to authenticate with Mercedes Me. This process requires interaction:

```bash
python setup_mercedes.py
```
Follow the on-screen instructions to complete the login flow. This will save the necessary token for the Mercedes connector.

### 4. Running as Systemd Services (Recommended for Deployment)

The project includes `systemd` service files for both the main optimizer and the web application. The `deploy.sh` script automates the process of setting up these services on a remote Raspberry Pi.

To manually enable and start the services (after `deploy.sh` has transferred them or you've copied them locally to `/etc/systemd/system/`):

```bash
sudo systemctl daemon-reload
sudo systemctl enable ev_smart_charger.service
sudo systemctl enable ev_web_app.service
sudo systemctl start ev_smart_charger.service
sudo systemctl start ev_web_app.service
```

### 5. Running Manually (for Development)

For development or testing, you can run the components manually:

**Main Optimizer:**
```bash
python src/main.py
```

**Web Application (using Flask's development server):**
```bash
PYTHONPATH=src python src/web_app.py
# The web app will be available at http://0.0.0.0:5000 (or http://localhost:5000)
```

## Development Conventions

*   **Modular Design:** The project is split into logical modules (connectors, optimizer, database, web).
*   **Configuration Management:** Uses `config/settings.yaml` for base configuration and `data/user_settings.json` for user-specific, dynamic preferences. `data/manual_overrides.json`, `data/manual_status.json` and `data/optimizer_state.json` are used for operational state.
*   **Logging:** Centralized logging is configured in `src/main.py`, outputting to `ev_charger.log` and stdout.
*   **API Integration:** Connectors handle interaction with external APIs.
*   **Web Framework:** Flask is used for the web dashboard.
*   **Deployment:** `systemd` services and `deploy.sh` script facilitate deployment to a Raspberry Pi.
