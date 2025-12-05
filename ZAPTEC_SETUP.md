# Zaptec Charger Integration Setup Guide

## Översikt

EV Smart Charger kan styra din Zaptec laddbox för att:
- Starta/stoppa laddning automatiskt
- Justera laddström (ampere)
- Läsa laddstatus
- Optimera laddning baserat på elpris

---

## Förutsättningar

1. **Zaptec laddbox installerad och ansluten till WiFi**
2. **Zaptec-konto** (skapat via Zaptec-appen)
3. **Installation ID** från Zaptec Portal

---

## Steg 1: Hitta dina Zaptec-uppgifter

### A. Inloggningsuppgifter

- **Email:** Din Zaptec-kontomail
- **Lösenord:** Ditt Zaptec-kontolösenord

### B. Installation ID

#### Metod 1: Via Zaptec-appen

1. Öppna Zaptec-appen på telefonen
2. Välj din laddbox
3. Gå till **Inställningar** → **Information**
4. Hitta **"Installation ID"** eller **"Installation"**
5. Kopiera numret (format: `12345`)

#### Metod 2: Via Zaptec Portal

1. Gå till https://portal.zaptec.com
2. Logga in med dina uppgifter
3. Välj din installation
4. Installation ID visas i URL:en eller under installationsinformation

---

## Steg 2: Uppdatera config/settings.yaml

Redigera `/home/peccz/ev_smart_charger/config/settings.yaml`:

```yaml
charger:
  zaptec:
    username: "din@email.se"
    password: "ditt_zaptec_lösenord"
    installation_id: "12345"  # Ditt Installation ID
```

**OBS:**
- Använd samma email/lösenord som i Zaptec-appen
- Installation ID är ett nummer (5-6 siffror vanligtvis)

---

## Steg 3: Deploy till Raspberry Pi

Från din lokala maskin:

```bash
cd /home/peccz/AI/ev_smart_charger
./deploy_generic.sh
```

Detta kommer automatiskt:
- Kopiera uppdaterad `settings.yaml` till RPi
- Starta om tjänsterna

---

## Steg 4: Verifiera Zaptec-anslutning

### SSH till RPi och testa:

```bash
ssh peccz@100.100.118.62
cd /home/peccz/ev_smart_charger

# Test Zaptec API
./venv/bin/python << 'EOF'
import sys
sys.path.insert(0, "src")
import yaml
from connectors.zaptec import ZaptecCharger

with open("config/settings.yaml") as f:
    config = yaml.safe_load(f)

charger = ZaptecCharger(config['charger']['zaptec'])
print("Zaptec initialized")

# Test get_status
status = charger.get_status()
print(f"Status: charging={status['is_charging']}, power={status['power_kw']}kW, energy={status['session_energy']}kWh")

# NOTE: start_charging() och stop_charging() testar vi inte här
# eftersom de skulle faktiskt starta/stoppa laddningen!
print("\nZaptec connection OK!")
EOF
```

### Förväntat resultat:

```
Zaptec initialized
Authenticating with Zaptec API...
Status: charging=True, power=11.0kW, energy=15.3kWh
Zaptec connection OK!
```

---

## Zaptec API-funktioner

Systemet kan nu:

### 1. Hämta status
```python
status = charger.get_status()
# Returns: {
#   'is_charging': bool,
#   'power_kw': float,
#   'session_energy': float
# }
```

### 2. Starta laddning
```python
charger.start_charging()
```

### 3. Stoppa laddning
```python
charger.stop_charging()
```

### 4. Justera laddström
```python
charger.set_charging_current(16)  # 16 ampere (=11 kW på 3-fas)
```

---

## Laddströmmar (3-fas 400V)

| Ampere | Effekt (kW) | Användning |
|--------|-------------|------------|
| 6A     | 4.2 kW      | Minimal laddning |
| 10A    | 6.9 kW      | Långsam laddning |
| 16A    | 11.0 kW     | Standard laddning |
| 20A    | 13.8 kW     | Snabb laddning (kräver 20A-säkring) |
| 32A    | 22.0 kW     | Max laddning (kräver 32A-säkring och kompatibel bil) |

**OBS:** EQV max 11 kW, Leaf max 6.6 kW

---

## Automatisk laddningskontroll

Med Zaptec konfigurerad kan systemet nu:

### Scenario 1: Lågt elpris + bil ansluten + låg SoC
```
→ Systemet startar automatiskt laddning
```

### Scenario 2: Högt elpris + bil ansluten
```
→ Systemet stoppar/pausar laddning
→ Väntar på billigare timmar
```

### Scenario 3: Målnivå nådd (target_soc)
```
→ Systemet stoppar laddning automatiskt
```

---

## Felsökning

### Problem: "Authentication failed"

**Orsak:** Fel användarnamn/lösenord

**Lösning:**
1. Dubbelkolla email och lösenord i settings.yaml
2. Testa logga in på portal.zaptec.com med samma uppgifter
3. Om du har bytt lösenord nyligen, uppdatera settings.yaml

### Problem: "Installation ID not found"

**Orsak:** Fel Installation ID

**Lösning:**
1. Gå till portal.zaptec.com
2. Verifiera ditt Installation ID
3. Uppdatera settings.yaml med rätt nummer

### Problem: "API rate limit exceeded"

**Orsak:** För många API-anrop

**Lösning:**
1. Systemet anropar Zaptec max 1 gång per timme
2. Om du testar manuellt, vänta 1 minut mellan anrop
3. Zaptec API har begränsningar för att skydda deras servrar

### Problem: "Connection timeout"

**Orsak:** Nätverksproblem

**Lösning:**
1. Kontrollera att RPi har internetåtkomst
2. Testa: `curl https://api.zaptec.com`
3. Kontrollera firewall-inställningar

---

## Säkerhet

### API-säkerhet:
- Credentials sparas lokalt i `config/settings.yaml`
- Filen är **inte** i Git (skyddad av .gitignore)
- Endast RPi har tillgång till credentials

### Laddningssäkerhet:
- Systemet har inbyggda begränsningar:
  - Startar/stoppar max 1 gång per timme
  - Följer bilens max laddeffekt
  - Respekterar target_soc-inställningar

### Manuell kontroll:
- Du kan alltid använda Zaptec-appen för att styra manuellt
- Manuella kommandon från appen har alltid prioritet
- Systemet detekterar manuella ändringar

---

## Avancerad konfiguration

### Optimeringslogik

Systemet beslutar om laddning baserat på:

```python
decision = optimizer.suggest_action(
    vehicle=car,
    prices=spot_prices,
    weather=forecast
)

if decision['action'] == 'CHARGE' and car_status['plugged_in']:
    charger.start_charging()
elif decision['action'] == 'IDLE':
    charger.stop_charging()
```

### Anpassa beslutslogik

Redigera `src/optimizer/engine.py` för att:
- Ändra priskänslighet
- Justera target_soc-trösklar
- Lägga till egna regler

---

## Testa systemet

### Full test-cykel:

```bash
# 1. Anslut bil till Zaptec-laddare
# 2. SSH till RPi
ssh peccz@100.100.118.62

# 3. Trigga en manuell körning
cd /home/peccz/ev_smart_charger
./venv/bin/python src/main.py

# 4. Övervaka loggen
tail -f ~/ev_charger.log
```

### Vad ska hända:

```
2025-12-05 08:30:01 - INFO - Fetching spot prices...
2025-12-05 08:30:02 - INFO - Fetched 96 prices
2025-12-05 08:30:03 - INFO - Current price: 0.85 SEK/kWh
2025-12-05 08:30:04 - INFO - Mercedes EQV: SoC=45%, plugged_in=True
2025-12-05 08:30:05 - INFO - Decision: CHARGE (current price in cheapest 3 hours)
2025-12-05 08:30:06 - INFO - Zaptec: Sending START command
2025-12-05 08:30:07 - INFO - Charging started successfully
```

---

## Exempel på fullständig konfiguration

```yaml
charger:
  zaptec:
    username: "per.andersson@email.se"
    password: "MinSäkraLösen123!"
    installation_id: "98765"

cars:
  mercedes_eqv:
    capacity_kwh: 90
    max_charge_kw: 11  # Matchar Zaptec vid 16A
    target_soc: 80

  nissan_leaf:
    capacity_kwh: 40
    max_charge_kw: 6.6  # Leaf-begränsning
    target_soc: 80

optimization:
  price_buffer_threshold: 0.10  # Ladda om pris < 10% över medel
  planning_horizon_days: 3      # Titta 3 dagar framåt
```

---

## Schemaläggning

Systemet kör automatiskt varje timme (01 minuter efter):

```
00:01 - Kontrollera priser, väder, bilstatus
01:01 - Kontrollera priser, väder, bilstatus
02:01 - Kontrollera priser, väder, bilstatus
...
```

Detta betyder att:
- Om du ansluter bilen kl 14:30, så kollar systemet kl 15:01
- Om elpriset ändras, justeras beslut inom max 1 timme
- Ändringar träder i kraft nästa hela timme

---

## Nästa steg

Med Zaptec integrerad har du nu:

1. ✅ Automatisk laddningsstyrning
2. ✅ Prisoptimerad laddning
3. ✅ Väderbaserad planering
4. ✅ Webbgränssnitt för övervakning

**Grattis!** 🎉 Ditt EV Smart Charger-system är nu fullt funktionellt!

---

## Support & Felsökning

Vid problem:

1. **Loggar:** `tail -f ~/ev_charger.log`
2. **Service status:** `sudo systemctl status ev_smart_charger.service`
3. **Zaptec Portal:** https://portal.zaptec.com
4. **Manuell test:** Kör `./venv/bin/python src/main.py` manuellt

---

**Lycka till med smart laddning!** ⚡🚗
