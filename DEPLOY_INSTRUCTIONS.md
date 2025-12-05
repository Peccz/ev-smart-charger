# 🚀 EV Smart Charger - Deployment Instructions

## Översikt

Detta projekt använder en **generisk deployment-process** som automatiskt detekterar projektets sökvägar på både lokal maskin och Raspberry Pi.

**Inga hårdkodade sökvägar** - allt fungerar oavsett var projektet är installerat!

---

## 📋 Förutsättningar

### På din lokala maskin:
- Git installerat och konfigurerat
- SSH-åtkomst till Raspberry Pi via Tailscale eller lokalt nätverk
- Projektet klonat från GitHub

### På Raspberry Pi:
- SSH-åtkomst aktiverad
- Python 3 installerat
- Git installerat
- Tillräckligt med diskutrymme (~500 MB)

---

## 🎯 Snabb Deployment

### Metod 1: Automatisk Deployment (Rekommenderad)

```bash
# Från din lokala maskin i projektmappen
chmod +x deploy_generic.sh
./deploy_generic.sh
```

Det är allt! Skriptet gör automatiskt:
1. ✓ Detekterar git repository root (lokalt)
2. ✓ Detekterar git repository root (RPi)
3. ✓ Pushar ändringar till GitHub
4. ✓ Pullar ändringar på RPi
5. ✓ Kopierar konfigurationsfiler
6. ✓ Skapar/uppdaterar Python virtual environment
7. ✓ Deployer systemd services
8. ✓ Startar om tjänsterna
9. ✓ Verifierar att allt fungerar

### Metod 2: Manuell Deployment

Om du vill göra det steg-för-steg:

```bash
# 1. Push till GitHub
git add .
git commit -m "Update deployment"
git push origin main

# 2. SSH till RPi
ssh peccz@100.100.118.62

# 3. Uppdatera kod
cd ~/ev_smart_charger  # eller var projektet ligger
git pull origin main

# 4. Uppdatera dependencies
./venv/bin/pip install -r requirements.txt

# 5. Starta om services
sudo systemctl restart ev_smart_charger.service
sudo systemctl restart ev_web_app.service

# 6. Verifiera status
sudo systemctl status ev_smart_charger.service
sudo systemctl status ev_web_app.service
```

---

## 🔧 Konfiguration

### Hemligheter och inställningar

Filen `config/settings.yaml` innehåller känslig information (API-nycklar, lösenord) och **ska INTE** checkas in i Git.

**Första gången:**
1. Skapa `config/settings.yaml` lokalt baserat på mallen
2. Fyll i dina API-nycklar och inställningar
3. Kör `deploy_generic.sh` - filen kopieras automatiskt till RPi

**Vid uppdateringar:**
- Om du ändrar `settings.yaml` lokalt körs deployment-skriptet igen
- Filen kopieras automatiskt till RPi

### Exempel settings.yaml:

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
    vin: "W1K..."
    capacity_kwh: 90
    max_charge_kw: 11
    target_soc: 80

  nissan_leaf:
    vin: ""
    capacity_kwh: 40
    max_charge_kw: 6.6
    target_soc: 80

charger:
  zaptec:
    username: "din_email@example.com"
    password: "ditt_lösenord"
    installation_id: "12345"
```

---

## 📊 Systemd Services

Projektet använder två systemd-tjänster:

### 1. ev_smart_charger.service
- **Funktion:** Kör huvudoptimerings-loopen
- **Schemaläggning:** Körs varje timme (01 minuter efter)
- **Loggar:** `~/ev_charger.log`

### 2. ev_web_app.service
- **Funktion:** Webb-gränssnitt för övervakning och kontroll
- **Port:** 5000
- **URL:** http://100.100.118.62:5000

### Hantera services:

```bash
# Starta om
sudo systemctl restart ev_smart_charger.service
sudo systemctl restart ev_web_app.service

# Status
sudo systemctl status ev_smart_charger.service
sudo systemctl status ev_web_app.service

# Loggar
sudo journalctl -u ev_smart_charger.service -f
sudo journalctl -u ev_web_app.service -f

# Stoppa/starta
sudo systemctl stop ev_smart_charger.service
sudo systemctl start ev_smart_charger.service
```

---

## 🔍 Verifiering efter Deployment

### 1. Kontrollera att services körs

```bash
ssh peccz@100.100.118.62
sudo systemctl status ev_smart_charger.service
sudo systemctl status ev_web_app.service
```

Du ska se **active (running)** ✅

### 2. Testa webb-gränssnittet

Öppna i webbläsare:
- Tailscale: `http://100.100.118.62:5000`
- Lokalt nätverk: `http://raspberrypi.local:5000` eller `http://192.168.X.X:5000`

### 3. Kontrollera loggar

```bash
ssh peccz@100.100.118.62
tail -f ~/ev_charger.log
```

Du ska se:
- Spotpris hämtning
- Väderprognoser
- Fordonsstatus
- Laddningsbeslut

---

## 🐛 Felsökning

### Problem: Tjänsten startar inte

```bash
# Kolla detaljerade loggar
sudo journalctl -u ev_smart_charger.service -n 100

# Testa manuellt
cd ~/ev_smart_charger/ev_smart_charger/src
../venv/bin/python main.py
```

### Problem: Kan inte nå webb-gränssnittet

```bash
# Kontrollera att tjänsten körs
sudo systemctl status ev_web_app.service

# Kontrollera att port 5000 är öppen
sudo netstat -tulpn | grep 5000

# Testa från RPi själv
curl http://localhost:5000
```

### Problem: Import-fel

```bash
# Installera om dependencies
cd ~/ev_smart_charger
./venv/bin/pip install -r requirements.txt --force-reinstall
```

### Problem: Konfigurationsfilen saknas

```bash
# Kopiera manuellt från lokal maskin
scp config/settings.yaml peccz@100.100.118.62:~/ev_smart_charger/config/
```

---

## 📁 Filstruktur på RPi

Efter deployment ser strukturen ut så här:

```
~/ev_smart_charger/
├── config/
│   └── settings.yaml          # Din konfiguration (kopierad)
├── data/
│   └── ev_charger.db          # SQLite databas
├── ev_smart_charger/
│   ├── src/
│   │   ├── main.py            # Huvudprogram
│   │   ├── connectors/        # API-kopplingar
│   │   ├── database/          # Databas-hantering
│   │   └── optimizer/         # Optimeringsmotorn
│   └── venv/                  # Python virtual environment
├── deploy_generic.sh          # Deployment-skript
├── ev_smart_charger.service   # Systemd core service
├── ev_web_app.service         # Systemd web service
└── requirements.txt
```

---

## 🎯 Vad händer vid deployment?

### Automatisk process:

1. **Git-detektering**
   - Hittar automatiskt projektets root lokalt
   - Hittar automatiskt projektets root på RPi
   - Ingen hårdkodad path behövs!

2. **Koduppdatering**
   - Pushar lokala ändringar till GitHub
   - Pullar ändringar på RPi från GitHub

3. **Konfiguration**
   - Kopierar `config/settings.yaml` (om den finns)
   - Skapar `data/` mapp för databas

4. **Python-miljö**
   - Skapar virtual environment (om inte finns)
   - Installerar/uppdaterar alla dependencies

5. **Systemd services**
   - Uppdaterar service-filer med korrekta sökvägar
   - Installerar i `/etc/systemd/system/`
   - Aktiverar auto-start vid boot
   - Startar om tjänsterna

6. **Verifiering**
   - Kontrollerar att båda tjänsterna körs
   - Visar status

---

## 🔄 Uppdatera efter ändringar

Efter att du har gjort ändringar i koden:

```bash
# Från lokal maskin
./deploy_generic.sh
```

Klart! Allt annat sker automatiskt.

---

## 🚀 Första Deployment (Ny installation)

Om projektet inte finns på RPi än:

```bash
# 1. Skriptet detekterar att projektet saknas
# 2. Klonar automatiskt från GitHub
# 3. Fortsätter med normal deployment

./deploy_generic.sh
```

Skriptet hanterar både nya installationer och uppdateringar!

---

## 📊 Övervaka systemet

### Realtidsloggar:

```bash
# Core service
ssh peccz@100.100.118.62 'tail -f ~/ev_charger.log'

# Web service
ssh peccz@100.100.118.62 'sudo journalctl -u ev_web_app.service -f'
```

### Dashboard:
- Öppna `http://100.100.118.62:5000` i webbläsare
- Se aktuell status för bilar, laddare, priser
- Kontrollera optimeringslogiken

---

## ✅ Checklista efter Deployment

- [ ] Båda services visar **active (running)**
- [ ] Webb-gränssnitt går att nå
- [ ] Loggar visar korrekt data (spotpris, väder, fordonsstatus)
- [ ] Databas skapas i `data/ev_charger.db`
- [ ] Konfigurationsfil finns på plats
- [ ] Första optimerings-körning lyckades

---

## 🔗 Relaterade filer

- `deploy_generic.sh` - Automatiskt deployment-skript
- `ev_smart_charger.service` - Core service definition
- `ev_web_app.service` - Web service definition
- `config/settings.yaml` - Konfiguration (ej i Git)

---

## 💡 Tips

1. **Alltid testa lokalt först** innan deployment
2. **Använd Tailscale** för säker fjärråtkomst
3. **Säkerhetskopiera settings.yaml** på säker plats
4. **Övervaka loggar** efter första deployment
5. **Testa manuellt** om något inte fungerar automatiskt

---

## 🤖 Support

Vid problem, kontrollera:
1. Loggar: `tail -f ~/ev_charger.log`
2. Service status: `sudo systemctl status ev_smart_charger.service`
3. Manuell körning: `cd ~/ev_smart_charger/ev_smart_charger/src && ../venv/bin/python main.py`

---

**Deployment framgångsrik!** 🎉

Ditt EV Smart Charger-system körs nu på Raspberry Pi och optimerar laddning baserat på elpris, väder och fordonsbehov.
