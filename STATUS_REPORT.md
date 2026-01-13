# Status Report - EV Smart Charger
Date: 2026-01-13

## Current Status
The charging system is operational and performing core duties correctly. Optimization, car identification, and charging control are working as intended. However, the Web GUI has display issues.

### ✅ Working Features
- **Smart Charging:** Optimizes based on spot prices and departure time.
- **Critical Charging:** Forces charge if deadline is near (verified).
- **Car Identification:** Correctly identifies Mercedes (3-phase/L3) and Nissan (1-phase L2).
- **History:** Logs sessions with split costs (Grid/Spot) and efficiency.
- **Config:** Secrets and settings are separated.

### ⚠️ Known Issues
1.  **Climate Controls Missing in GUI:**
    - The `climate_entity_id` is returning `null` in the `/api/status` response, causing buttons to hide.
    - Diagnostics show `ConfigManager` loads it correctly in isolation, but `web_app.py` fails to retrieve it.
    - **Suspect:** Context issue or variable scope in `api_status`.

2.  **SoC Display Discrepancy:**
    - GUI sometimes shows 90% SoC when car is at 23%.
    - **Suspect:** Logic collision between `manual_status` (from slider) and `optimizer_state` (from car API).

3.  **Stability:**
    - Web app has experienced crashes due to unhandled NoneTypes in `optimizer_state`. (Patched with safety checks).

## Plan for Next Session
1.  **Fix Climate Buttons:**
    - Debug `web_app.py` config loading.
    - Verify `full_merged_config` structure at runtime inside Flask context.
    
2.  **Fix SoC Display:**
    - Review `build_car` logic in `web_app.py`.
    - Ensure API data always overrides manual slider if API data is fresh.

3.  **Cleanup:**
    - Remove temporary debug scripts (`debug_config.py`, `test_zaptec_details.py`).
    - Verify log rotation.
