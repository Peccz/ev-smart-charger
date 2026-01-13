import pytest
import pandas as pd
from datetime import datetime, timedelta
from src.optimizer.engine import Optimizer

@pytest.fixture
def base_config():
    return {
        'optimization': {
            'price_buffer_threshold': 0.10,
            'planning_horizon_days': 3
        }
    }

class MockVehicle:
    def __init__(self, soc=50, plugged=True):
        self.name = "Mercedes EQV"
        self.capacity_kwh = 90
        self.max_charge_kw = 11
        self.soc = soc
        self.plugged = plugged
    
    def get_status(self):
        return {
            "soc": self.soc,
            "plugged_in": self.plugged,
            "is_home": True
        }

def test_optimizer_chooses_cheapest_hours(base_config):
    optimizer = Optimizer(base_config)
    optimizer.long_term_history_avg = 1.0 # 1 SEK/kWh avg
    
    vehicle = MockVehicle(soc=20) # Needs charge
    
    # Create 24 hours of prices: first 5 are expensive, next 5 are cheap
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    prices = []
    for i in range(24):
        prices.append({
            "time_start": (now + timedelta(hours=i)).isoformat(),
            "price_sek": 3.0 if i < 5 else 0.5 # High first, then low
        })
    
    # Test 1: Current hour is expensive (Index 0)
    decision = optimizer.suggest_action(vehicle, prices, [])
    assert decision['action'] == "IDLE" # Should wait
    
    # Test 2: Current hour is cheap (Shift prices so index 0 is cheap)
    cheap_prices = prices[5:] + prices[:5]
    decision = optimizer.suggest_action(vehicle, cheap_prices, [])
    assert decision['action'] == "CHARGE" # Should charge now

def test_optimizer_forces_charge_near_deadline(base_config):
    optimizer = Optimizer(base_config)
    optimizer.long_term_history_avg = 1.0
    
    vehicle = MockVehicle(soc=10) # Critically low
    
    # Set departure time to 2 hours from now
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    dep_time = (now + timedelta(hours=2)).strftime("%H:%M")
    
    # We need to mock _get_user_settings to return this departure time
    optimizer._get_user_settings = lambda: {"departure_time": dep_time, "mercedes_eqv_min_soc": 80}
    
    # Even if price is high, it should charge because deadline is near
    prices = [{"time_start": (now + timedelta(hours=i)).isoformat(), "price_sek": 5.0} for i in range(24)]
    
    decision = optimizer.suggest_action(vehicle, prices, [])
    assert decision['action'] == "CHARGE"
    assert "CRITICAL" in decision['reason']
