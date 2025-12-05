# HomeAssistant Integration Setup Guide

## Översikt

EV Smart Charger kan hämta realtids-data om dina fordon från HomeAssistant. Detta ger:
- Exakt batterinivå (SoC%)
- Räckvidd
- Anslutningsstatus (plugged in / unplugged)
- Laddningsstatus

---

## Förutsättningar

1. **HomeAssistant installerat och körande**
   - Antingen lokalt (http://homeassistant.local:8123)
   - Eller via extern åtkomst

2. **Fordon integrerade i HomeAssistant**
   - Mercedes-Benz (via officiell integration)
   - Nissan Leaf (via Nissan Connect integration)

---

## Steg 1: Skapa Long-Lived Access Token i HomeAssistant

1. Logga in på din HomeAssistant
2. Klicka på ditt namn längst ner i vänster sidebar
3. Scrolla ner till **"Long-Lived Access Tokens"**
4. Klicka **"Create Token"**
5. Ge den ett namn: `EV Smart Charger`
6. Kopiera token (den visas bara EN gång!)
7. Spara token säkert

---

## Steg 2: Hitta Entity IDs för dina fordon

### I HomeAssistant:

1. Gå till **Developer Tools** → **States**
2. Sök efter ditt fordons sensorer

### Mercedes EQV - Vanliga Entity IDs:

```
sensor.mercedes_me_eqv_300_state_of_charge          # Batterinivå (%)
sensor.mercedes_me_eqv_300_electric_range          # Räckvidd (km)
binary_sensor.mercedes_me_eqv_300_plug_status      # Laddkabel ansluten
sensor.mercedes_me_eqv_300_charging_status         # Laddningsstatus
```

### Nissan Leaf - Vanliga Entity IDs:

```
sensor.leaf_battery                                 # Batterinivå (%)
sensor.leaf_range                                   # Räckvidd (km)
binary_sensor.leaf_plug_status                      # Laddkabel ansluten
sensor.leaf_charging_status                         # Laddningsstatus
```

**Tips:** Entity IDs kan variera beroende på din HomeAssistant-konfiguration!

---

## Steg 3: Uppdatera config/settings.yaml

Redigera `/home/peccz/ev_smart_charger/config/settings.yaml`:

```yaml
cars:
  mercedes_eqv:
    vin: "W1K..."
    capacity_kwh: 90
    max_charge_kw: 11
    target_soc: 80
    # HomeAssistant Integration
    ha_url: "http://192.168.1.100:8123"  # DIN HomeAssistant IP
    ha_token: "eyJ0eXAiOiJKV1QiLCJhbGc..."  # Token från steg 1
    ha_merc_soc_entity_id: "sensor.mercedes_me_eqv_300_state_of_charge"
    ha_merc_plugged_entity_id: "binary_sensor.mercedes_me_eqv_300_plug_status"
    ha_merc_range_entity_id: "sensor.mercedes_me_eqv_300_electric_range"

  nissan_leaf:
    vin: ""
    capacity_kwh: 40
    max_charge_kw: 6.6
    target_soc: 80
    # HomeAssistant Integration
    ha_url: "http://192.168.1.100:8123"  # Samma som ovan
    ha_token: "eyJ0eXAiOiJKV1QiLCJhbGc..."  # Samma token
    ha_leaf_soc_entity_id: "sensor.leaf_battery"
    ha_leaf_plugged_entity_id: "binary_sensor.leaf_plug_status"
    ha_leaf_range_entity_id: "sensor.leaf_range"
```

**Viktigt:**
- Byt `http://192.168.1.100:8123` till din faktiska HomeAssistant-adress
- Klistra in din riktiga token
- Använd korrekta entity IDs från steg 2

---

## Steg 4: Deploy till Raspberry Pi

Från din lokala maskin:

```bash
cd /home/peccz/AI/ev_smart_charger
./deploy_generic.sh
```

Detta kommer automatiskt:
- Pusha ändringar till GitHub
- Uppdatera kod på RPi
- Kopiera uppdaterad `settings.yaml`
- Starta om tjänsterna

---

## Steg 5: Verifiera att det fungerar

### SSH till RPi och testa:

```bash
ssh peccz@100.100.118.62
cd /home/peccz/ev_smart_charger

# Testa manuellt
./venv/bin/python << 'EOF'
import sys
sys.path.insert(0, "src")
import yaml
from connectors.vehicles import MercedesEQV, NissanLeaf

with open("config/settings.yaml") as f:
    config = yaml.safe_load(f)

# Test Mercedes
eqv = MercedesEQV(config['cars']['mercedes_eqv'])
status = eqv.get_status()
print(f"Mercedes: SoC={status['soc']}%, Range={status['range_km']}km, Plugged={status['plugged_in']}")

# Test Nissan
leaf = NissanLeaf(config['cars']['nissan_leaf'])
status = leaf.get_status()
print(f"Nissan: SoC={status['soc']}%, Range={status['range_km']}km, Plugged={status['plugged_in']}")
EOF
```

### Förväntat resultat:

```
Mercedes: SoC=75%, Range=245km, Plugged=True
Nissan: SoC=82%, Range=190km, Plugged=False
```

Om du ser riktiga värden (inte 0%) så fungerar det! 🎉

---

## Felsökning

### Problem: "HA credentials incomplete"

**Orsak:** Token eller URL saknas i settings.yaml

**Lösning:**
1. Kontrollera att `ha_url` och `ha_token` är ifyllda
2. Verifiera att inga mellanslag eller citattecken saknas
3. Kör deploy igen

### Problem: "Error fetching state from HA"

**Orsak:** Fel entity ID eller nätverksproblem

**Lösning:**
1. Verifiera entity IDs i HomeAssistant Developer Tools → States
2. Testa från RPi:
   ```bash
   curl -H "Authorization: Bearer <TOKEN>" \
        http://<HA_IP>:8123/api/states/sensor.mercedes_me_eqv_300_state_of_charge
   ```
3. Kontrollera att RPi kan nå HomeAssistant (ping, firewall)

### Problem: "Connection refused"

**Orsak:** HomeAssistant är inte nåbar från RPi

**Lösning:**
1. Använd IP-adress istället för `homeassistant.local`
2. Kontrollera firewall på HomeAssistant-servern
3. Verifiera att port 8123 är öppen
4. Testa från RPi: `curl http://<HA_IP>:8123`

### Problem: SoC är alltid 0%

**Orsak:** Fordonet inte uppdaterat i HomeAssistant

**Lösning:**
1. Gå till HomeAssistant och trigga manuell uppdatering av fordon
2. Vänta 5-10 minuter på att fordonet vaknar
3. Vissa fordon uppdaterar bara vid laddning/körning

---

## Alternativ: Utan HomeAssistant

Om du inte har HomeAssistant kan systemet fortfarande fungera:

1. Lämna `ha_url` och `ha_token` tomma
2. Systemet använder då mock-data (simulated values)
3. Du kan manuellt justera värdena i kod om nödvändigt

---

## Nästa steg

Efter HomeAssistant-integration fungerar:

1. **Automatisk övervakning**
   - Systemet kollar batterinivå varje timme
   - Sparar historik i databas

2. **Smart laddning**
   - Beslutar när laddning ska starta baserat på:
     - Aktuell SoC
     - Målvärde (target_soc)
     - Elpris
     - Väderprognos

3. **Webbgränssnitt**
   - Se aktuell status på http://100.100.118.62:5000
   - Historik och grafer

---

## Exempel på fullständig konfiguration

```yaml
location:
  city: "Upplands Väsby"
  latitude: 59.5196
  longitude: 17.9285
  timezone: "Europe/Stockholm"

grid:
  provider: "Eon"
  region: "SE3"

cars:
  mercedes_eqv:
    vin: "W1K2901234567890"
    capacity_kwh: 90
    max_charge_kw: 11
    target_soc: 80
    ha_url: "http://192.168.1.50:8123"
    ha_token: "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
    ha_merc_soc_entity_id: "sensor.mercedes_me_eqv_300_state_of_charge"
    ha_merc_plugged_entity_id: "binary_sensor.mercedes_me_eqv_300_plug_status"
    ha_merc_range_entity_id: "sensor.mercedes_me_eqv_300_electric_range"

  nissan_leaf:
    vin: ""
    capacity_kwh: 40
    max_charge_kw: 6.6
    target_soc: 80
    ha_url: "http://192.168.1.50:8123"
    ha_token: "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
    ha_leaf_soc_entity_id: "sensor.leaf_battery"
    ha_leaf_plugged_entity_id: "binary_sensor.leaf_plug_status"
    ha_leaf_range_entity_id: "sensor.leaf_range"

charger:
  zaptec:
    username: "din@email.se"
    password: "ditt_lösenord"
    installation_id: "12345-67890"

optimization:
  price_buffer_threshold: 0.10
  planning_horizon_days: 3
```

---

**Klart!** 🎉

Nu har du kopplat dina elbilar från HomeAssistant till EV Smart Charger för intelligent laddningsoptimering!
