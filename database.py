import sqlite3
import os
import logging
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Dict, Any, List
import threading

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_name: str = "fatigue.db"):
        self.db_name = db_name
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._initialized = False
    
    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                self.db_name, 
                check_same_thread=False,
                timeout=20.0,
                isolation_level=None  # Autocommit mode for simplicity
            )
            self._local.connection.row_factory = sqlite3.Row
            self._local.connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection.execute("PRAGMA synchronous=NORMAL")
        return self._local.connection
    
    @contextmanager
    def transaction(self):
        conn = self._get_connection()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.execute("COMMIT")
        except Exception as e:
            conn.execute("ROLLBACK")
            raise e
    
    def init_db(self):
        with self._init_lock:
            if self._initialized:
                return
            
            try:
                with self.transaction() as conn:
                    cursor = conn.cursor()
                    
                    # Drop existing tables for clean schema
                    cursor.execute("DROP TABLE IF EXISTS fatigue_alerts")
                    cursor.execute("DROP TABLE IF EXISTS fatigue_trips")
                    
                    # Trips table
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS fatigue_trips (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            end_time TIMESTAMP,
                            distance_km REAL,
                            duration_minutes INTEGER,
                            status TEXT DEFAULT 'active',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    
                    # Alerts table with indexing
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS fatigue_alerts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            trip_id INTEGER NOT NULL,
                            alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            duration_seconds REAL NOT NULL,
                            alert_type TEXT DEFAULT 'eyes_closed',
                            severity TEXT DEFAULT 'medium',
                            FOREIGN KEY (trip_id) REFERENCES fatigue_trips(id)
                        )
                    """)
                    
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_alerts_trip 
                        ON fatigue_alerts(trip_id)
                    """)
                    
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_alerts_time 
                        ON fatigue_alerts(alert_time)
                    """)
                
                self._initialized = True
                logger.info("Database initialized successfully")
                
            except Exception as e:
                logger.error(f"Database initialization failed: {e}")
                raise
    
    def create_trip(self) -> int:
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO fatigue_trips (start_time, status) VALUES (?, ?)",
                (datetime.now(), 'active')
            )
            return cursor.lastrowid
    
    def end_trip(self, trip_id: int, distance: Optional[float], duration: Optional[int]):
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE fatigue_trips 
                SET end_time=?, distance_km=?, duration_minutes=?, status=?
                WHERE id=?
            """, (datetime.now(), distance, duration, 'completed', trip_id))
    
    def log_alert(self, trip_id: int, duration: float, alert_type: str = 'eyes_closed'):
        severity = 'low' if duration < 2.0 else 'medium' if duration < 5.0 else 'high'
        
        try:
            with self.transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO fatigue_alerts 
                    (trip_id, alert_time, duration_seconds, alert_type, severity) 
                    VALUES (?, ?, ?, ?, ?)
                """, (trip_id, datetime.now(), duration, alert_type, severity))
        except Exception as e:
            logger.error(f"Failed to log alert: {e}")
            # Don't raise - alert logging should not break the detection loop
    
    def get_trip_stats(self, trip_id: int) -> Dict[str, Any]:
        with self.transaction() as conn:
            cursor = conn.cursor()
            
            # Alert summary
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_alerts,
                    SUM(CASE WHEN alert_type = 'eyes_closed' THEN 1 ELSE 0 END) as fatigue_alerts,
                    SUM(CASE WHEN alert_type = 'no_face' THEN 1 ELSE 0 END) as no_face_alerts,
                    MAX(duration_seconds) as max_duration,
                    AVG(duration_seconds) as avg_duration
                FROM fatigue_alerts
                WHERE trip_id = ?
            """, (trip_id,))
            
            alert_stats = dict(cursor.fetchone())
            
            # Trip info
            cursor.execute("""
                SELECT start_time, end_time, duration_minutes
                FROM fatigue_trips
                WHERE id = ?
            """, (trip_id,))
            
            trip_info = dict(cursor.fetchone() or {})
            
            return {
                'trip_id': trip_id,
                'alert_summary': alert_stats,
                'trip_info': trip_info
            }
    
    def get_recent_trips(self, limit: int = 10) -> List[Dict]:
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.*, COUNT(a.id) as alert_count
                FROM fatigue_trips t
                LEFT JOIN fatigue_alerts a ON t.id = a.trip_id
                GROUP BY t.id
                ORDER BY t.start_time DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

# Global instance
_db_manager = DatabaseManager()

def init_db():
    _db_manager.init_db()

def create_trip() -> int:
    return _db_manager.create_trip()

def end_trip(trip_id: int, distance: Optional[float], duration: Optional[int]):
    _db_manager.end_trip(trip_id, distance, duration)

def log_alert(trip_id: int, duration: float, alert_type: str = 'eyes_closed'):
    _db_manager.log_alert(trip_id, duration, alert_type)

def get_trip_stats(trip_id: int) -> Dict[str, Any]:
    return _db_manager.get_trip_stats(trip_id)