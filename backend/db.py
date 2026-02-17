import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "staysense.db"
REQUIRED_TABLES = {
    "spot",
    "community_signal",
    "osm_poi",
    "osm_zone",
    "osm_road",
    "open_data_event",
    "data_source_state",
    "admin_user",
}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            # Some deployments run with read-only db mounts; continue without WAL.
            pass
        schema_sql = """
            CREATE TABLE IF NOT EXISTS spot (
                id TEXT PRIMARY KEY,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                osm_area_type TEXT NOT NULL CHECK (osm_area_type IN ('residential', 'industrial', 'commercial', 'parking', 'nature')),
                road_type TEXT NOT NULL CHECK (road_type IN ('residential', 'primary', 'secondary', 'service', 'unknown')),
                distance_police_m INTEGER NOT NULL,
                distance_fire_m INTEGER NOT NULL,
                distance_hospital_m INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS local_event (
                id TEXT PRIMARY KEY,
                spot_id TEXT NOT NULL,
                event_type TEXT NOT NULL CHECK (event_type IN ('market', 'waste', 'event', 'construction')),
                start_datetime TEXT NOT NULL,
                end_datetime TEXT NOT NULL,
                risk_modifier INTEGER NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (spot_id) REFERENCES spot(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS community_signal (
                id TEXT PRIMARY KEY,
                spot_id TEXT NOT NULL,
                signal_type TEXT NOT NULL CHECK (signal_type IN ('calm', 'noise', 'knock', 'police')),
                hashed_device TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                day_bucket TEXT NOT NULL,
                FOREIGN KEY (spot_id) REFERENCES spot(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS osm_poi (
                id TEXT PRIMARY KEY,
                poi_type TEXT NOT NULL CHECK (poi_type IN ('police', 'fire', 'hospital')),
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                source TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS osm_zone (
                id TEXT PRIMARY KEY,
                zone_type TEXT NOT NULL CHECK (zone_type IN ('residential', 'industrial', 'commercial', 'parking', 'nature')),
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                source TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS osm_road (
                id TEXT PRIMARY KEY,
                road_type TEXT NOT NULL CHECK (road_type IN ('residential', 'primary', 'secondary', 'service')),
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                source TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS open_data_event (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL CHECK (event_type IN ('market', 'waste', 'event', 'construction')),
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                start_datetime TEXT NOT NULL,
                end_datetime TEXT NOT NULL,
                risk_modifier INTEGER NOT NULL,
                source TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS data_source_state (
                source_name TEXT PRIMARY KEY,
                imported_at TEXT NOT NULL,
                record_count INTEGER NOT NULL,
                notes TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_user (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_signal_spot_timestamp
              ON community_signal (spot_id, timestamp);

            CREATE UNIQUE INDEX IF NOT EXISTS ux_signal_spot_device_day
              ON community_signal (spot_id, hashed_device, day_bucket);

            CREATE INDEX IF NOT EXISTS idx_local_event_spot_window
              ON local_event (spot_id, start_datetime, end_datetime);

            CREATE INDEX IF NOT EXISTS idx_osm_poi_type
              ON osm_poi (poi_type);

            CREATE INDEX IF NOT EXISTS idx_osm_zone_type
              ON osm_zone (zone_type);

            CREATE INDEX IF NOT EXISTS idx_open_data_event_window
              ON open_data_event (start_datetime, end_datetime);

            CREATE INDEX IF NOT EXISTS idx_open_data_event_source
              ON open_data_event (source);
            """
        try:
            conn.executescript(schema_sql)
        except sqlite3.OperationalError as exc:
            if "readonly" not in str(exc).lower():
                raise
            # In read-only mode, continue if schema is already present.
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            existing = {str(row["name"]) for row in rows}
            missing = REQUIRED_TABLES - existing
            if missing:
                raise
