import pandas as pd
import numpy as np
import logging

# Setup minimal logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()

def generate_year_data():
    """Generates 1 year of realistic hourly SE3 price data (øre/kWh)."""
    np.random.seed(42) # For reproducible results
    hours = 365 * 24
    
    # 1. Seasonal Trend (Winter high, Summer low) - Cosine wave
    # Peak at start/end of year, Trough in middle
    x = np.linspace(0, 2 * np.pi, hours)
    seasonal_base = 80 + 60 * np.cos(x) # Base varies between 20 and 140
    
    # 2. Daily Cycle (Morning/Evening peaks)
    # 2 peaks per day
    daily_x = np.linspace(0, 365 * 4 * np.pi, hours)
    daily_var = 20 * np.sin(daily_x - 2) # Shifted to match peaks
    
    # 3. Volatility/Wind (Random noise)
    noise = np.random.normal(0, 30, hours)
    
    # Combine
    prices = seasonal_base + daily_var + noise
    
    # Ensure no negative prices (simplify for this test, though they exist)
    prices = np.maximum(5, prices) 
    
    # Add some extreme spikes (Cold snap / No wind)
    spike_indices = np.random.choice(hours, 50, replace=False)
    prices[spike_indices] += 200
    
    dates = pd.date_range(start='2024-01-01', periods=hours, freq='h')
    return pd.DataFrame({'time': dates, 'price': prices})

def run_simulation():
    logger.info("--- SIMULERAR LADDSTRATEGIER (365 Dagar) ---")
    df = generate_year_data()
    
    avg_spot_price = df['price'].mean()
    logger.info(f"Genomsnittligt spotpris över året: {avg_spot_price:.2f} öre/kWh")
    
    # Windows to test (in hours)
    windows = {
        "3 Dagar (Snabb)": 3 * 24,
        "7 Dagar (Balanserad)": 7 * 24,
        "30 Dagar (Långsiktig)": 30 * 24
    }
    
    threshold_factor = 0.90 # Charge if price is 10% lower than average
    
    results = []
    
    for name, window_hours in windows.items():
        # Calculate Rolling Average
        df[f'ma_{name}'] = df['price'].rolling(window=window_hours, min_periods=24).mean()
        
        # Simulate Charging Decision
        # Logic: If current price < 0.9 * MovingAverage -> CHARGE
        # We filter out the first 'window' hours to be fair (data warmup)
        valid_data = df.iloc[window_hours:].copy()
        
        # Identify charging hours
        valid_data['charge'] = valid_data['price'] < (valid_data[f'ma_{name}'] * threshold_factor)
        
        # Calculate Stats
        charged_hours = valid_data[valid_data['charge']]
        num_hours = len(charged_hours)
        avg_charge_cost = charged_hours['price'].mean()
        savings = avg_spot_price - avg_charge_cost
        savings_percent = (savings / avg_spot_price) * 100
        
        results.append({
            "Strategi": name,
            "Laddtimmar (antal)": num_hours,
            "Snittpris (laddning)": f"{avg_charge_cost:.2f} öre",
            "Besparing vs Spot": f"{savings_percent:.1f}%"
        })

    # Print Table
    print(f"{'Strategi':<25} | {'Snittpris':<15} | {'Besparing':<10} | {'Volym (h)'}")
    print("-" * 65)
    for r in results:
        print(f"{r['Strategi']:<25} | {r['Snittpris (laddning)']:<15} | {r['Besparing vs Spot']:<10} | {r['Laddtimmar (antal)']}")

if __name__ == "__main__":
    run_simulation()
