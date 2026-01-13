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
                energy_added_kwh REAL DEFAULT 0,
                cost_sek REAL DEFAULT 0,
                start_soc INTEGER,
                end_soc INTEGER,
                start_odometer INTEGER,
                end_odometer INTEGER
            )
        ''')
        
        # Migrations for existing tables
        try:
            cursor.execute("ALTER TABLE charging_sessions ADD COLUMN start_soc INTEGER")
        except sqlite3.OperationalError: pass
        try:
            cursor.execute("ALTER TABLE charging_sessions ADD COLUMN end_soc INTEGER")
        except sqlite3.OperationalError: pass
        try:
            cursor.execute("ALTER TABLE charging_sessions ADD COLUMN start_odometer INTEGER")
        except sqlite3.OperationalError: pass
        try:
            cursor.execute("ALTER TABLE charging_sessions ADD COLUMN end_odometer INTEGER")
        except sqlite3.OperationalError: pass
        try:
            cursor.execute("ALTER TABLE charging_sessions ADD COLUMN cost_spot_sek REAL DEFAULT 0")
        except sqlite3.OperationalError: pass
        try:
            cursor.execute("ALTER TABLE charging_sessions ADD COLUMN cost_grid_sek REAL DEFAULT 0")
        except sqlite3.OperationalError: pass
        try:
            cursor.execute("ALTER TABLE charging_sessions ADD COLUMN avg_power_kw REAL")
        except sqlite3.OperationalError: pass

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

    def start_session(self, vehicle_id, start_soc, odometer):
        """Starts a new charging session and returns the session ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO charging_sessions (vehicle_id, start_time, start_soc, start_odometer, energy_added_kwh, cost_sek)
            VALUES (?, ?, ?, ?, 0, 0)
        ''', (vehicle_id, datetime.now(), start_soc, odometer))
        session_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return session_id

    def update_session(self, session_id, energy_delta, spot_cost, grid_cost):
        """Accumulates energy and cost for an active session."""
        total_cost = spot_cost + grid_cost
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE charging_sessions 
            SET energy_added_kwh = energy_added_kwh + ?,
                cost_sek = cost_sek + ?,
                cost_spot_sek = cost_spot_sek + ?,
                cost_grid_sek = cost_grid_sek + ?
            WHERE id = ?
        ''', (energy_delta, total_cost, spot_cost, grid_cost, session_id))
        conn.commit()
        conn.close()

    def end_session(self, session_id, end_soc, odometer):
        """Finalizes a session and calculates average power."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Fetch data to calculate speed
        cursor.execute("SELECT start_time, energy_added_kwh FROM charging_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        avg_power = 0
        if row:
            try:
                # Handle both string and datetime objects
                start_time_str = row[0]
                if isinstance(start_time_str, str):
                    # SQLite might return different formats, handle common ISO
                    start_time = datetime.fromisoformat(start_time_str.split('.')[0].replace(' ', 'T'))
                else:
                    start_time = start_time_str
                
                energy = row[1]
                duration_hours = (datetime.now() - start_time).total_seconds() / 3600.0
                if duration_hours > 0.05: # At least 3 minutes to be valid
                    avg_power = energy / duration_hours
            except Exception as e:
                print(f"Error calculating session speed: {e}")

        cursor.execute('''
            UPDATE charging_sessions 
            SET end_time = ?,
                end_soc = ?,
                end_odometer = ?,
                avg_power_kw = ?
            WHERE id = ?
        ''', (datetime.now(), end_soc, odometer, avg_power, session_id))
        conn.commit()
        conn.close()

    def get_learned_charge_speed(self, vehicle_id, default_speed):
        """Returns the average power from recent sessions or the default if no data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Look at last 5 valid sessions (> 1 kWh added to avoid noise)
        cursor.execute('''
            SELECT avg_power_kw FROM charging_sessions 
            WHERE vehicle_id = ? AND avg_power_kw > 0.5 AND energy_added_kwh > 1.0
            ORDER BY end_time DESC LIMIT 5
        ''', (vehicle_id,))
        speeds = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        if speeds:
            learned_avg = sum(speeds) / len(speeds)
            # Cap at 120% of default to prevent data errors, but allow lower
            return min(learned_avg, default_speed * 1.2)
        return default_speed

    def get_charging_history(self, limit=50):
        """Returns charging history with formatted fields."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row # Access by name
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM charging_sessions 
            WHERE end_time IS NOT NULL 
            ORDER BY start_time DESC 
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

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