from flask import Flask, render_template, jsonify, request
import json
import os
import sqlite3
from datetime import datetime, timedelta
import pandas as pd

# Import specific connectors just to fetch live data for the Planning UI
# (In a larger app, we would cache this in DB, but let's fetch fresh for now)
from connectors.spot_price import SpotPriceService
from connectors.weather import WeatherService

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")

SETTINGS_PATH = "data/user_settings.json"
OVERRIDES_PATH = "data/manual_overrides.json"
STATE_PATH = "data/optimizer_state.json"

DEFAULT_SETTINGS = {
    "mercedes_target": 80,
    "nissan_target": 80,
    "departure_time": "07:00",
    "smart_buffering": True
}

# Initialize services (lightweight)
spot_service = SpotPriceService()
weather_service = WeatherService(59.5196, 17.9285) # Upplands Väsby coords

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

@app.route('/planning')
def planning_page():
    return render_template('planning.html')

@app.route('/settings')
def settings_page():
    return render_template('settings.html')

@app.route('/api/status')
def api_status():
    settings = get_settings()
    overrides = get_overrides()
    state = get_optimizer_state()
    
    # Flatten state
    cars = []
    for k, v in state.items():
        v['name'] = k
        cars.append(v)
        
    # Sort by urgency score (highest first)
    cars.sort(key=lambda x: x.get('urgency_score', 0), reverse=True)
    
    priority_car_id = None
    if cars and cars[0].get('urgency_score', 0) > 0:
        priority_car_id = cars[0]['id']

    cars_data = {}
    
    def build_car(name, key_id, target_key):
        car_state = state.get(name, {})
        if not car_state:
             for k, v in state.items():
                 if name.split()[0] in k:
                     car_state = v
                     break
        
        target = settings.get(target_key, 80)
        soc = car_state.get('soc', 0)
        plugged_in = car_state.get('plugged_in', False)
        urgency = car_state.get('urgency_score', 0)
        
        is_priority = (key_id == priority_car_id)
        needs_plugging = False
        urgency_msg = ""
        swap_msg = ""
        
        if is_priority and not plugged_in and urgency > 0:
            needs_plugging = True
            urgency_msg = "Denna bil MÅSTE laddas nu!"
            other_car = cars[1] if len(cars) > 1 and cars[0]['id'] == key_id else cars[0]
            if other_car.get('plugged_in'):
                swap_msg = f"Koppla ur {other_car.get('name', 'den andra bilen')}!"

        if not is_priority and plugged_in and priority_car_id and priority_car_id != key_id:
             p_car = next((c for c in cars if c['id'] == priority_car_id), None)
             if p_car and not p_car.get('plugged_in'):
                 needs_plugging = True 
                 urgency_msg = "Var god koppla ur denna bil."
                 swap_msg = f"Byt till {p_car.get('name')}!"

        return {
            "name": name,
            "id": key_id,
            "soc": soc,
            "target": target,
            "plugged_in": plugged_in,
            "override": overrides.get(key_id),
            "action": car_state.get('action', 'IDLE'),
            "reason": car_state.get('reason', '-'),
            "urgency_score": urgency,
            "is_priority": is_priority,
            "needs_plugging": needs_plugging,
            "urgency_msg": urgency_msg,
            "swap_msg": swap_msg
        }

    cars_data['mercedes'] = build_car("Mercedes EQV", "mercedes_eqv", "mercedes_target")
    cars_data['nissan'] = build_car("Nissan Leaf", "nissan_leaf", "nissan_target")
    
    return jsonify({
        "cars": cars_data,
        "system": {
            "departure": settings.get('departure_time', '07:00')
        }
    })

@app.route('/api/plan')
def api_plan():
    """
    Returns price data and charging plan for the UI graph.
    """
    try:
        prices = spot_service.get_prices_upcoming()
        weather = weather_service.get_forecast()
        
        # Get logic from state
        state = get_optimizer_state()
        
        # Add simple analysis text
        analysis = []
        if prices:
            df = pd.DataFrame(prices)
            avg = df['price_sek'].mean()
            min_p = df['price_sek'].min()
            analysis.append(f"Snittpris: {avg:.2f} kr (Lägst: {min_p:.2f} kr)")
        
        if weather:
            df_w = pd.DataFrame(weather)
            avg_wind = df_w['wind_kmh'].mean()
            analysis.append(f"Vindprognos: {avg_wind:.1f} km/h (Medel)")
            if avg_wind > 20:
                analysis.append("🌪️ Mycket vind -> Priserna sjunker troligen!")
        
        return jsonify({
            "prices": prices, # List of {time_start, price_sek}
            "weather": weather,
            "analysis": analysis
        })
    except Exception as e:
        print(e)
        return jsonify({"error": str(e)})

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
    set_override(data.get('vehicle_id'), data.get('action'), data.get('duration', 60))
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    os.makedirs("data", exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)