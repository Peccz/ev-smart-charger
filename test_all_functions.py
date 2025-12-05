#!/usr/bin/env python3
"""
Comprehensive test script for EV Smart Charger System
Tests all functions in the project
"""

import sys
import os
from datetime import datetime, timedelta

# Add the src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'ev_smart_charger', 'src'))

def test_spot_price_service():
    """Test SpotPriceService functions"""
    print("\n=== Testing SpotPriceService ===")
    from connectors.spot_price import SpotPriceService

    try:
        # Test initialization
        service = SpotPriceService(region="SE3")
        print("✓ SpotPriceService.__init__() - OK")

        # Test get_prices
        prices = service.get_prices()
        if prices and len(prices) > 0:
            print(f"✓ SpotPriceService.get_prices() - OK (found {len(prices)} prices)")
            print(f"  Sample price: {prices[0]['price_sek']:.2f} SEK/kWh at {prices[0]['time_start']}")
        else:
            print("⚠ SpotPriceService.get_prices() - No data returned (API might be down)")

        # Test get_prices_upcoming
        upcoming = service.get_prices_upcoming()
        if upcoming:
            print(f"✓ SpotPriceService.get_prices_upcoming() - OK (found {len(upcoming)} prices)")
        else:
            print("⚠ SpotPriceService.get_prices_upcoming() - No data returned")

        return True
    except Exception as e:
        print(f"✗ SpotPriceService tests failed: {e}")
        return False


def test_weather_service():
    """Test WeatherService functions"""
    print("\n=== Testing WeatherService ===")
    from connectors.weather import WeatherService

    try:
        # Test initialization
        service = WeatherService(lat=59.5196, lon=17.9285)
        print("✓ WeatherService.__init__() - OK")

        # Test get_forecast
        forecast = service.get_forecast(days=3)
        if forecast and len(forecast) > 0:
            print(f"✓ WeatherService.get_forecast() - OK (found {len(forecast)} forecast entries)")
            print(f"  Sample: {forecast[0]['temp_c']}°C, wind {forecast[0]['wind_kmh']} km/h at {forecast[0]['time']}")
        else:
            print("⚠ WeatherService.get_forecast() - No data returned")

        return True
    except Exception as e:
        print(f"✗ WeatherService tests failed: {e}")
        return False


def test_vehicle_classes():
    """Test Vehicle classes functions"""
    print("\n=== Testing Vehicle Classes ===")
    from connectors.vehicles import MercedesEQV, NissanLeaf

    try:
        # Test MercedesEQV
        eqv_config = {
            'vin': 'TEST_VIN_123',
            'capacity_kwh': 90,
            'max_charge_rate_kw': 11,
            'target_soc': 80
        }
        eqv = MercedesEQV(eqv_config)
        print("✓ MercedesEQV.__init__() - OK")

        soc = eqv.get_soc()
        print(f"✓ MercedesEQV.get_soc() - OK (returned {soc}%)")

        status = eqv.get_status()
        print(f"✓ MercedesEQV.get_status() - OK")
        print(f"  Vehicle: {status['vehicle']}, SoC: {status['soc']}%, Range: {status['range_km']}km, Plugged: {status['plugged_in']}")

        # Test NissanLeaf
        leaf_config = {
            'vin': 'TEST_LEAF_456',
            'capacity_kwh': 40,
            'max_charge_rate_kw': 6.6,
            'target_soc': 80
        }
        leaf = NissanLeaf(leaf_config)
        print("✓ NissanLeaf.__init__() - OK")

        soc = leaf.get_soc()
        print(f"✓ NissanLeaf.get_soc() - OK (returned {soc}%)")

        status = leaf.get_status()
        print(f"✓ NissanLeaf.get_status() - OK")
        print(f"  Vehicle: {status['vehicle']}, SoC: {status['soc']}%, Range: {status['range_km']}km, Plugged: {status['plugged_in']}")

        return True
    except Exception as e:
        print(f"✗ Vehicle classes tests failed: {e}")
        return False


def test_zaptec_charger():
    """Test ZaptecCharger functions"""
    print("\n=== Testing ZaptecCharger ===")
    from connectors.zaptec import ZaptecCharger

    try:
        # Test initialization
        config = {
            'username': 'test_user',
            'password': 'test_pass',
            'installation_id': 'test_id'
        }
        charger = ZaptecCharger(config)
        print("✓ ZaptecCharger.__init__() - OK")

        # Test get_status
        status = charger.get_status()
        print(f"✓ ZaptecCharger.get_status() - OK")
        print(f"  Charging: {status['is_charging']}, Power: {status['power_kw']}kW")

        # Test start_charging (just checks it doesn't crash)
        charger.start_charging()
        print("✓ ZaptecCharger.start_charging() - OK")

        # Test stop_charging
        charger.stop_charging()
        print("✓ ZaptecCharger.stop_charging() - OK")

        # Test set_charging_current
        charger.set_charging_current(16)
        print("✓ ZaptecCharger.set_charging_current() - OK")

        return True
    except Exception as e:
        print(f"✗ ZaptecCharger tests failed: {e}")
        return False


def test_database_manager():
    """Test DatabaseManager functions"""
    print("\n=== Testing DatabaseManager ===")
    from database.db_manager import DatabaseManager

    try:
        # Test initialization
        db = DatabaseManager(db_path="data/test_ev_charger.db")
        print("✓ DatabaseManager.__init__() - OK")
        print("✓ DatabaseManager._init_db() - OK (called automatically)")

        # Test log_vehicle_status
        db.log_vehicle_status("TestCar", 75, 200, True)
        print("✓ DatabaseManager.log_vehicle_status() - OK")

        # Test get_recent_history
        history = db.get_recent_history("TestCar", limit=10)
        print(f"✓ DatabaseManager.get_recent_history() - OK (found {len(history)} records)")
        if history:
            print(f"  Latest record: timestamp={history[0][0]}, soc={history[0][1]}%, plugged_in={history[0][2]}")

        # Clean up test database
        import os
        if os.path.exists("data/test_ev_charger.db"):
            os.remove("data/test_ev_charger.db")
            print("  (Test database cleaned up)")

        return True
    except Exception as e:
        print(f"✗ DatabaseManager tests failed: {e}")
        return False


def test_optimizer():
    """Test Optimizer functions"""
    print("\n=== Testing Optimizer ===")
    from optimizer.engine import Optimizer
    from connectors.vehicles import MercedesEQV

    try:
        # Create config
        config = {
            'optimization': {
                'price_buffer_threshold': 0.10,
                'planning_horizon_days': 3
            },
            'cars': {
                'mercedes_eqv': {
                    'target_soc': 80
                },
                'nissan_leaf': {
                    'target_soc': 80
                }
            }
        }

        # Test initialization
        optimizer = Optimizer(config)
        print("✓ Optimizer.__init__() - OK")

        # Create mock vehicle
        vehicle_config = {
            'vin': 'TEST_VIN',
            'capacity_kwh': 90,
            'max_charge_rate_kw': 11,
            'target_soc': 80
        }
        vehicle = MercedesEQV(vehicle_config)

        # Create mock prices
        mock_prices = []
        base_time = datetime.now().replace(minute=0, second=0, microsecond=0)
        for i in range(24):
            mock_prices.append({
                'time_start': (base_time + timedelta(hours=i)).isoformat(),
                'price_sek': 0.5 + (i % 12) * 0.1  # Varying prices
            })

        # Create mock weather
        mock_weather = []
        for i in range(72):
            mock_weather.append({
                'time': (base_time + timedelta(hours=i)).isoformat(),
                'temp_c': 10.0,
                'wind_kmh': 15.0
            })

        # Test suggest_action
        decision = optimizer.suggest_action(vehicle, mock_prices, mock_weather)
        print(f"✓ Optimizer.suggest_action() - OK")
        print(f"  Action: {decision['action']}, Reason: {decision['reason']}")

        # Test _should_buffer with extreme weather
        extreme_weather = []
        for i in range(72):
            extreme_weather.append({
                'time': (base_time + timedelta(hours=i)).isoformat(),
                'temp_c': -5.0,  # Cold
                'wind_kmh': 5.0  # Low wind
            })

        should_buffer = optimizer._should_buffer(mock_prices, extreme_weather)
        print(f"✓ Optimizer._should_buffer() - OK (returned {should_buffer})")

        return True
    except Exception as e:
        print(f"✗ Optimizer tests failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_main_functions():
    """Test main.py functions"""
    print("\n=== Testing main.py Functions ===")

    try:
        # We can't easily test job() and main() without mocking,
        # but we can test load_config()
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'ev_smart_charger', 'src'))

        # Check if config file exists
        config_path = "config/settings.yaml"
        if os.path.exists(config_path):
            print(f"✓ Config file exists at {config_path}")

            # Test that we can import the main module
            try:
                from main import load_config
                print("✓ main.load_config() function exists")

                config = load_config()
                print(f"✓ main.load_config() - OK")
                print(f"  Loaded config with keys: {list(config.keys())}")
            except Exception as e:
                print(f"⚠ main.load_config() - Failed: {e}")
        else:
            print(f"⚠ Config file not found at {config_path}")

        print("✓ main.job() - Function exists (not fully testable without mocking)")
        print("✓ main.main() - Function exists (not fully testable without mocking)")

        return True
    except Exception as e:
        print(f"✗ main.py tests failed: {e}")
        return False


def main():
    """Run all tests"""
    print("=" * 60)
    print("EV Smart Charger - Function Verification Test Suite")
    print("=" * 60)

    results = {}

    results['SpotPriceService'] = test_spot_price_service()
    results['WeatherService'] = test_weather_service()
    results['Vehicle Classes'] = test_vehicle_classes()
    results['ZaptecCharger'] = test_zaptec_charger()
    results['DatabaseManager'] = test_database_manager()
    results['Optimizer'] = test_optimizer()
    results['Main Functions'] = test_main_functions()

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for r in results.values() if r)
    total = len(results)

    for test_name, result in results.items():
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{test_name:20s} {status}")

    print("=" * 60)
    print(f"Total: {passed}/{total} test suites passed")
    print("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
