from connectors.spot_price import SpotPriceService
import json

try:
    service = SpotPriceService()
    prices = service.get_prices_upcoming()
    print(f"Fetched {len(prices)} prices.")
    if prices:
        print("Sample prices:")
        for p in prices[:5]:
            print(p)
        
        # Check for variance
        values = [p['price_sek'] for p in prices]
        min_p = min(values)
        max_p = max(values)
        avg_p = sum(values) / len(values)
        print(f"Min: {min_p}, Max: {max_p}, Avg: {avg_p}")
        
        if max_p - min_p < 0.01:
            print("WARNING: Prices are extremely flat!")
    else:
        print("No prices returned.")

except Exception as e:
    print(f"Error: {e}")
