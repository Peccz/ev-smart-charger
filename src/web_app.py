from flask import Flask, render_template, jsonify, request
import json
import os
import math
from datetime import datetime, timedelta
import pandas as pd

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

spot_service = SpotPriceService()
weather_service = WeatherService(59.5196, 17.9285)

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
        
        # UI Logic for Alerts
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

        # Start Time Logic (Quick Estimate for UI)
        # If IDLE but urgency > 0, when will it start?
        start_time_text = ""
        if plugged_in and car_state.get('action') == 'IDLE' and urgency > 0:
             # The frontend graph calculation is better, but let's try to give a hint here
             start_time_text = "Startar senare..."

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
            "swap_msg": swap_msg,
            "start_time_text": start_time_text
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
    try:
        prices = spot_service.get_prices_upcoming()
        weather = weather_service.get_forecast()
        settings = get_settings()
        state = get_optimizer_state()

        df = pd.DataFrame(prices)
        analysis = []
        charging_plan = [] # Array of 0 or 1 matching prices length
        
        # Determine priority car to plan for
        cars = []
        for k, v in state.items():
            v['name'] = k
            cars.append(v)
        cars.sort(key=lambda x: x.get('urgency_score', 0), reverse=True)
        
        priority_car = cars[0] if cars else None
        
        if priority_car and priority_car.get('urgency_score', 0) > 0:
            # Simulate logic
            hours_needed = math.ceil(priority_car.get('urgency_score'))
            
            # Sort prices by value
            df_sorted = df.sort_values(by='price_sek', ascending=True)
            # Pick cheapest N hours
            cheapest_hours = df_sorted.head(hours_needed)['time_start'].tolist()
            
            # Build plan array
            for p in prices:
                is_charging = 1 if p['time_start'] in cheapest_hours else 0
                charging_plan.append(is_charging)
                
            # Add Analysis Text
            start_time = min(cheapest_hours) if cheapest_hours else "-"
            start_time_fmt = datetime.fromisoformat(start_time).strftime("%H:%M") if cheapest_hours else "-"
            
            analysis.append(f"Planerar laddning för {priority_car['name']}.")
            analysis.append(f"Behov: {hours_needed} timmar.")
            analysis.append(f"Starttid: {start_time_fmt}.")
            analysis.append(f"Valde billigaste timmarna (Snitt: {df_sorted.head(hours_needed)['price_sek'].mean():.2f} kr).")
        else:
            charging_plan = [0] * len(prices)
            analysis.append("Inget laddbehov just nu.")

        return jsonify({
            "prices": prices,
            "plan": charging_plan,
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
