import json
from datetime import datetime
import statistics

# Constants from spot_price.py
GRID_FEE = 0.25
RETAILER_FEE = 0.05
ENERGY_TAX = 0.5488
VAT_RATE = 0.25

def calculate_total_price(spot_price_incl_vat_sek):
    fees_vat = (GRID_FEE + RETAILER_FEE) * VAT_RATE
    total_price = spot_price_incl_vat_sek + GRID_FEE + RETAILER_FEE + fees_vat + ENERGY_TAX
    return total_price

def analyze():
    try:
        with open('data_forecast.json', 'r') as f:
            forecasts = json.load(f)
        with open('data_actuals.json', 'r') as f:
            actuals_raw = json.load(f)
    except FileNotFoundError:
        print("Error: Files not found.")
        return

    # Convert actuals to a lookup dict: {"YYYY-MM-DDTHH": total_price}
    actual_lookup = {}
    for date_key, prices in actuals_raw.items():
        # prices is a list of floats (raw spot)
        for hour, raw_price in enumerate(prices):
            # Construct ISO timestamp prefix for lookup (YYYY-MM-DDTHH)
            # Assuming list is 00:00 to 23:00
            time_str = f"{date_key}T{hour:02d}"
            total_price = calculate_total_price(raw_price)
            actual_lookup[time_str] = total_price

    print(f"Loaded {len(actual_lookup)} actual price points.")
    
    # Analyze Forecasts
    # forecasts format: {"YYYY-MM-DD": [ {time_start, price_sek, source}, ... ]}
    
    errors = []
    
    print("\n--- Forecast Evaluation (Last 3 Generations) ---\n")
    
    # Analyze all Forecasts
    gen_dates = sorted(forecasts.keys())
    print(f"Available Generations: {gen_dates}")
    
    for gen_date in gen_dates: # Look at ALL forecast generations
        print(f"Generation Date: {gen_date}")
        print(f"{ 'Target Time':<20} | { 'Pred (SEK)':<10} | { 'Actual (SEK)':<12} | { 'Diff':<10} | { 'Source':<10}")
        print("-" * 75)
        
        batch_errors = []
        forecast_list = forecasts[gen_date]
        
        # Sort by target time
        forecast_list.sort(key=lambda x: x['time_start'])
        
        for point in forecast_list:
            # We only care about "Forecasted" values, not "Official" (which are cheating)
            # But let's show both to see if "Official" matches actuals (sanity check)
            
            ts = point['time_start'] # 2026-01-06T10:00:00+01:00 or similar
            # Normalize timestamp for lookup (remove seconds and timezone offset for simple matching)
            # Input: 2026-01-06T10:00:00 (from main.py isoformat)
            
            lookup_key = ts[:13] # YYYY-MM-DDTHH
            
            predicted = point['price_sek']
            source = point.get('source', 'Unknown')
            
            if lookup_key in actual_lookup:
                actual = actual_lookup[lookup_key]
                diff = predicted - actual
                
                # Only track error for pure Forecasts
                if source == "Forecasted":
                    batch_errors.append(abs(diff))
                    errors.append(abs(diff))
                
                # Print sample (every 6th hour or if error is large)
                hour = int(lookup_key.split('T')[1])
                if hour % 6 == 0 or abs(diff) > 1.0:
                    print(f"{lookup_key:<20} | {predicted:<10.2f} | {actual:<12.2f} | {diff:<10.2f} | {source}")
            else:
                # print(f"{lookup_key} not in actuals")
                pass
        
        if batch_errors:
            mae = statistics.mean(batch_errors)
            print("-" * 75)
            print(f"Mean Absolute Error (Forecasted Only): {mae:.2f} SEK\n")
        else:
            print("(No overlapping forecast/actual data found for evaluation)\n")

    if errors:
        total_mae = statistics.mean(errors)
        print(f"Overall MAE across all evaluated batches: {total_mae:.2f} SEK")

if __name__ == "__main__":
    analyze()
