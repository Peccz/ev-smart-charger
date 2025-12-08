import sqlite3
import os
from datetime import datetime

class DatabaseManager:
    def __init__(self, db_path="data/ev_charger.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table: Vehicle Status Log (Legacy/Simple)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vehicle_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id TEXT,
                timestamp DATETIME,
                soc INTEGER,
                range_km INTEGER,
                is_plugged_in BOOLEAN
            )
        ''')

        # Table: Charging Sessions (Summary)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS charging_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id TEXT,
                start_time DATETIME,
                end_time DATETIME,
                energy_added_kwh REAL,
                cost_sek REAL
            )
        ''')

        # Table: System Metrics (High resolution log for ML/Analytics)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                active_car_id TEXT,
                zaptec_power_kw REAL,
                zaptec_energy_kwh REAL,
                zaptec_mode TEXT,
                mercedes_soc INTEGER,
                mercedes_plugged BOOLEAN,
                nissan_soc INTEGER,
                nissan_plugged BOOLEAN,
                temp_c REAL,
                price_sek REAL
            )
        ''')
        
        conn.commit()
        conn.close()

    def log_vehicle_status(self, vehicle_id, soc, range_km, is_plugged_in):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO vehicle_log (vehicle_id, timestamp, soc, range_km, is_plugged_in)
            VALUES (?, ?, ?, ?, ?)
        ''', (vehicle_id, datetime.now(), soc, range_km, is_plugged_in))
        conn.commit()
        conn.close()

    def log_system_metrics(self, metrics):
        """
        Logs a snapshot of the entire system state.
        metrics: dict containing keys matching the table columns.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO system_metrics (
                timestamp, active_car_id, zaptec_power_kw, zaptec_energy_kwh, zaptec_mode,
                mercedes_soc, mercedes_plugged, nissan_soc, nissan_plugged,
                temp_c, price_sek
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now(),
            metrics.get('active_car_id'),
            metrics.get('zaptec_power_kw', 0.0),
            metrics.get('zaptec_energy_kwh', 0.0),
            metrics.get('zaptec_mode', 'UNKNOWN'),
            metrics.get('mercedes_soc', 0),
            metrics.get('mercedes_plugged', False),
            metrics.get('nissan_soc', 0),
            metrics.get('nissan_plugged', False),
            metrics.get('temp_c', 0.0),
            metrics.get('price_sek', 0.0)
        ))
        conn.commit()
        conn.close()

    def get_recent_history(self, vehicle_id, limit=100):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT timestamp, soc, is_plugged_in FROM vehicle_log
            WHERE vehicle_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (vehicle_id, limit))
        data = cursor.fetchall()
        conn.close()
        return data