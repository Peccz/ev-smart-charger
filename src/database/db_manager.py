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
        
        # Table: Vehicle Status Log (SoC history)
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

        # Table: Charging Sessions
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
