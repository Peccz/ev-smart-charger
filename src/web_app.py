from flask import Flask, render_template, jsonify, request
import json
import os
import sqlite3
from datetime import datetime, timedelta

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")

# Paths
SETTINGS_PATH = "data/user_settings.json"
OVERRIDES_PATH = "data/manual_overrides.json"
STATE_PATH = "data/optimizer_state.json"

# Defaults
DEFAULT_SETTINGS = {
    "mercedes_target": 80,
    "nissan_target": 80,
    "departure_time": "07:00",
    "smart_buffering": True
}

def get_settings():
    if not os.path.exists(SETTINGS_PATH):
        return DEFAULT_SETTINGS
    try:
        with open(SETTINGS_PATH, 'r') as f:
            return json.load(f)
    except:
        return DEFAULT_SETTINGS

def save_settings(settings):
    with open(SETTINGS_PATH, 'w') as f:
        json.dump(settings, f, indent=2)

def get_overrides():
    if not os.path.exists(OVERRIDES_PATH):
        return {}
    try:
        with open(OVERRIDES_PATH, 'r') as f:
            return json.load(f)
    except:
        return {}

def set_override(vehicle_id, action, duration_minutes=60):
    overrides = get_overrides()
    
    if action == "AUTO":
        if vehicle_id in overrides:
            del overrides[vehicle_id]
    else:
        expiry = datetime.now() + timedelta(minutes=duration_minutes)
        overrides[vehicle_id] = {
            "action": action,
            "expires_at": expiry.isoformat()
        }
    
    with open(OVERRIDES_PATH, 'w') as f:
        json.dump(overrides, f, indent=2)

def get_optimizer_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, 'r') as f:
            return json.load(f)
    except:
        return {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/settings')
def settings_page():
    return render_template('settings.html')

@app.route('/api/status')
def api_status():
    settings = get_settings()
    overrides = get_overrides()
    state = get_optimizer_state()
    
    # Merge state with settings
    # Default structure if state file is empty
    cars_data = {}
    
    # Helper to build car object
    def build_car(name, key_id, target_key):
        # Find data in state (which is keyed by full name e.g. "Mercedes EQV")
        # We do a fuzzy match or direct lookup
        car_state = state.get(name, {})
        if not car_state:
             # Try finding by partial string
             for k, v in state.items():
                 if name.split()[0] in k:
                     car_state = v
                     break
        
        target = settings.get(target_key, 80)
        soc = car_state.get('soc', 0)
        plugged_in = car_state.get('plugged_in', False)
        
        # Urgency Logic:
        # If Soc < Target AND Not Plugged In -> Alert!
        needs_plugging = False
        urgency_msg = ""
        
        if soc < target and not plugged_in:
            needs_plugging = True
            diff = target - soc
            urgency_msg = f"Saknas {diff}% för att nå målet!"

        return {
            "name": name,
            "id": key_id,
            "soc": soc,
            "target": target,
            "plugged_in": plugged_in,
            "override": overrides.get(key_id),
            "action": car_state.get('action', 'IDLE'),
            "reason": car_state.get('reason', '-'),
            "needs_plugging": needs_plugging,
            "urgency_msg": urgency_msg
        }

    cars_data['mercedes'] = build_car("Mercedes EQV", "mercedes_eqv", "mercedes_target")
    cars_data['nissan'] = build_car("Nissan Leaf", "nissan_leaf", "nissan_target")
    
    return jsonify({
        "cars": cars_data,
        "system": {
            "departure": settings.get('departure_time', '07:00')
        }
    })

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'POST':
        data = request.json
        current = get_settings()
        current.update(data)
        save_settings(current)
        return jsonify({"status": "ok"})
    else:
        return jsonify(get_settings())

@app.route('/api/override', methods=['POST'])
def api_override():
    data = request.json
    vehicle_id = data.get('vehicle_id')
    action = data.get('action') 
    duration = data.get('duration', 60)
    
    set_override(vehicle_id, action, duration)
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    os.makedirs("data", exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)