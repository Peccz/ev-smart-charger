# EV Smart Charger

Intelligent laddstyrning för elbilar baserat på spotpriser, väderprognos och fordonsstatus.

## Översikt

EV Smart Charger optimerar laddning av Mercedes EQV och Nissan Leaf genom att:
- Ladda när elpriset är lågt
- Anpassa målnivå baserat på pristrend
- Respektera användarsättningar (min/max SoC, avgångstid)
- Styra Zaptec Go laddbox automatiskt

## Systemkrav

- Raspberry Pi 4 (eller motsvarande)
- Python 3.11+
- Zaptec Go laddbox
- HomeAssistant med Mercedes-Benz och Nissan Leaf integrationer

## Installation

Systemet körs på Raspberry Pi och startar automatiskt via systemd.

### Tjänster

Tre systemd-tjänster hanterar systemet:

```bash
# Core optimizer (kör varje minut)
sudo systemctl status ev_smart_charger.service

# Webb-dashboard
sudo systemctl status ev_web_app.service

# Monitor för Home Assistant ändringar
sudo systemctl status monitor.service
```

### Starta om tjänster

```bash
# Starta om alla tjänster
sudo systemctl restart ev_smart_charger.service ev_web_app.service monitor.service

# Eller individuellt
sudo systemctl restart ev_smart_charger.service
```

### Visa loggar

```bash
# Realtidslogg för core optimizer
sudo journalctl -u ev_smart_charger.service -f

# Senaste 100 rader
sudo journalctl -u ev_smart_charger.service -n 100

# Webb-appens logg
sudo journalctl -u ev_web_app.service -f

# Monitor-logg
sudo journalctl -u monitor.service -f
```

## Konfiguration

### Secrets (data/secrets.json)

Innehåller känslig information:

```json
{
  "home_assistant": {
    "url": "http://100.100.118.62:8123",
    "token": "YOUR_LONG_LIVED_TOKEN"
  },
  "zaptec": {
    "username": "your@email.com",
    "password": "your_password",
    "charger_id": "UUID"
  },
  "nissan": {
    "vin": "VIN_NUMBER",
    "username": "your@email.com",
    "password": "your_password"
  }
}
```

**VIKTIGT:** Denna fil kopieras INTE av deployment-skriptet för säkerhet.

### Användarsättningar (data/user_settings.json)

Uppdateras via webb-GUI:
- Min/Max SoC för varje bil
- Avgångstid
- Smart buffering on/off

### Återställa secrets.json

Om secrets.json skadas eller tas bort:

```bash
cd /home/peccz/ev_smart_charger
cp data/secrets.json.backup data/secrets.json  # Om backup finns
# Eller skapa ny från mall:
nano data/secrets.json
```

## Webb-Dashboard

Tillgängligt på: **http://100.100.118.62:5000**

### Funktioner:
- Realtidsstatus för båda fordonen
- Aktuella spotpriser och prognoser
- Manuell laddkontroll ("⚡ Ladda Nu", "Stop")
- Inställningar för SoC-nivåer
- Historikgrafer

## Manuell Styrning

### Via Webb-GUI:
1. Gå till http://100.100.118.62:5000
2. Klicka "⚡ Ladda Nu" för omedelbar laddning
3. Klicka "Stop" för att pausa laddning
4. Klicka "Auto" för att återgå till automatisk optimering

### Via SSH:

```bash
# Triggra en manuell körning direkt
ssh peccz@100.100.118.62
cd /home/peccz/ev_smart_charger
./venv/bin/python src/main.py
```

## Felsökning

### Problem: Tjänsten startar inte

```bash
# Kolla loggen för felmeddelanden
sudo journalctl -u ev_smart_charger.service -n 50

# Testa att köra manuellt för att se exakta fel
cd /home/peccz/ev_smart_charger
./venv/bin/python src/main.py
```

### Problem: Webb-dashboard inte nåbart

```bash
# Verifiera att tjänsten kör
sudo systemctl status ev_web_app.service

# Testa lokalt på RPi
curl http://localhost:5000

# Kolla att port 5000 är öppen
sudo netstat -tulpn | grep 5000
```

### Problem: Inga priser hämtas

```bash
# Testa manuellt
curl "https://www.elprisetjustnu.se/api/v1/prices/$(date +%Y)/$(date +%m-%d)_SE3.json"

# Kolla loggen
sudo journalctl -u ev_smart_charger.service | grep -i "spot\|price"
```

### Problem: HomeAssistant anslutning misslyckas

```bash
# Testa token manuellt
HA_URL="http://100.100.118.62:8123"
HA_TOKEN="your_token_here"

curl -H "Authorization: Bearer $HA_TOKEN" \
     "$HA_URL/api/states/sensor.urg48t_state_of_charge"
```

### Problem: Zaptec anslutning misslyckas

```bash
# Testa från RPi
cd /home/peccz/ev_smart_charger
./venv/bin/python << 'EOF'
import sys
sys.path.insert(0, "src")
from config_manager import ConfigManager
from connectors.zaptec import ZaptecCharger

config = ConfigManager.load_full_config()
charger = ZaptecCharger(config["charger"]["zaptec"])
status = charger.get_status()
print(f"Status: {status}")
EOF
```

## Databas

SQLite-databas i: `/home/peccz/ev_smart_charger/data/ev_charger.db`

### Inspektera data:

```bash
# Senaste fordonsstatus
sqlite3 data/ev_charger.db \
  "SELECT * FROM vehicle_log ORDER BY timestamp DESC LIMIT 10"

# Laddningssessioner
sqlite3 data/ev_charger.db \
  "SELECT * FROM charging_sessions ORDER BY start_time DESC LIMIT 5"

# System-metrics
sqlite3 data/ev_charger.db \
  "SELECT * FROM system_metrics ORDER BY timestamp DESC LIMIT 10"
```

## Deployment

Från utvecklingsmaskin:

```bash
cd /home/peccz/AI/ev_smart_charger
./deploy_generic.sh
```

Detta skript:
1. Committar ändringar till Git
2. Pushar till GitHub
3. Pullar på RPi
4. Startar om tjänsterna

**OBS:** `data/secrets.json` kopieras INTE - måste uppdateras manuellt vid behov.

## Arkitektur

### Projektstruktur

```
ev_smart_charger/
├── src/
│   ├── main.py                 # Core optimizer loop
│   ├── web_app.py             # Flask webb-app
│   ├── config_manager.py      # Centraliserad config
│   ├── connectors/
│   │   ├── spot_price.py      # Elpris API
│   │   ├── weather.py         # Väder API
│   │   ├── vehicles.py        # HA integration
│   │   └── zaptec.py          # Zaptec API
│   ├── optimizer/
│   │   └── engine.py          # Optimeringslogik
│   └── database/
│       └── db_manager.py      # SQLite hantering
├── config/
│   └── settings.yaml          # Bas-konfiguration
├── data/
│   ├── secrets.json           # API-nycklar (ej i Git)
│   ├── user_settings.json     # GUI-inställningar
│   ├── manual_overrides.json  # Manuella styrbeslut
│   └── ev_charger.db          # SQLite databas
└── monitor_changes.py         # HA change monitor
```

### Viktiga sökvägar

Alla sökvägar är **absoluta** via `config_manager.PROJECT_ROOT`:
- Detta garanterar att tjänsterna fungerar oavsett working directory
- Även om systemd kör från `/home/peccz/ev_smart_charger`, används absoluta vägar

## Support

Vid problem:
1. Kolla loggarna: `sudo journalctl -u ev_smart_charger.service -f`
2. Verifiera att alla tjänster kör: `systemctl status ev_*`
3. Testa komponenterna individuellt enligt Felsöknings-sektionen

## Licens

Privat projekt - Inte för publik distribution

---

**Utvecklad av:** Claude Code
**Status:** Produktionsklar (Fas 4 Complete)
**Senast uppdaterad:** 2025-12-09
