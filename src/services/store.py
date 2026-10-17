"""
Voyage persistence.

Two layers, because they answer different questions. A process-level registry holds live
`VoyageEngine` objects, since stepping a voyage needs the engine's internal state (which leg it
is steering, which alerts are open) and that is not worth serialising every tick. SQLite holds a
durable snapshot of every voyage, its ticks and its alerts, so a passage survives a restart and
can be exported or reviewed afterwards.

SQLite is the right choice here rather than a server database: the shipboard console is a single
rugged PC on a bridge with no infrastructure behind it, and the same file works unchanged at
NCPOR headquarters.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.voyage import VoyageEngine, VoyageState

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "polarnav.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS voyages (
    voyage_id      TEXT PRIMARY KEY,
    created_iso    TEXT NOT NULL,
    updated_iso    TEXT NOT NULL,
    status         TEXT NOT NULL,
    vessel_name    TEXT,
    ice_class      TEXT,
    origin_name    TEXT,
    destination_name TEXT,
    origin_lat     REAL,
    origin_lon     REAL,
    dest_lat       REAL,
    dest_lon       REAL,
    sim_hours      REAL,
    fuel_tonnes    REAL,
    distance_nm    REAL,
    state_json     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticks (
    voyage_id  TEXT NOT NULL,
    tick       INTEGER NOT NULL,
    sim_hours  REAL NOT NULL,
    latitude   REAL,
    longitude  REAL,
    tick_json  TEXT NOT NULL,
    PRIMARY KEY (voyage_id, tick)
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id   TEXT PRIMARY KEY,
    voyage_id  TEXT NOT NULL,
    tick       INTEGER,
    sim_hours  REAL,
    code       TEXT,
    severity   TEXT,
    message    TEXT,
    advisory   TEXT,
    latitude   REAL,
    longitude  REAL
);

CREATE INDEX IF NOT EXISTS idx_ticks_voyage ON ticks(voyage_id);
CREATE INDEX IF NOT EXISTS idx_alerts_voyage ON alerts(voyage_id);
"""


class VoyageStore:
    """Durable snapshots plus a registry of live engines."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._engines: Dict[str, VoyageEngine] = {}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            # Write-ahead logging so a reader (the dashboard) never blocks the writer (a voyage
            # stepping in the background).
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------- live engines
    def register(self, engine: VoyageEngine) -> str:
        self._engines[engine.state.voyage_id] = engine
        self.save(engine.state)
        return engine.state.voyage_id

    def engine(self, voyage_id: str) -> Optional[VoyageEngine]:
        return self._engines.get(voyage_id)

    def live_ids(self) -> List[str]:
        return list(self._engines.keys())

    def drop(self, voyage_id: str) -> None:
        self._engines.pop(voyage_id, None)

    # ------------------------------------------------------------ persistence
    def save(self, state: VoyageState) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = state.model_dump_json()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO voyages (voyage_id, created_iso, updated_iso, status, vessel_name,
                    ice_class, origin_name, destination_name, origin_lat, origin_lon, dest_lat,
                    dest_lon, sim_hours, fuel_tonnes, distance_nm, state_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(voyage_id) DO UPDATE SET
                    updated_iso=excluded.updated_iso, status=excluded.status,
                    sim_hours=excluded.sim_hours, fuel_tonnes=excluded.fuel_tonnes,
                    distance_nm=excluded.distance_nm, state_json=excluded.state_json
                """,
                (
                    state.voyage_id, state.created_iso, now, state.status, state.vessel_name,
                    state.ice_class, state.origin_name, state.destination_name,
                    state.origin[0], state.origin[1], state.destination[0], state.destination[1],
                    state.sim_hours, state.total_fuel_tonnes, state.distance_travelled_nm, payload,
                ),
            )
            for tick in state.ticks[-200:]:
                conn.execute(
                    "INSERT OR REPLACE INTO ticks (voyage_id, tick, sim_hours, latitude, longitude, tick_json)"
                    " VALUES (?,?,?,?,?,?)",
                    (state.voyage_id, tick.tick, tick.sim_hours, tick.latitude, tick.longitude,
                     tick.model_dump_json()),
                )
            for alert in state.alerts:
                conn.execute(
                    "INSERT OR REPLACE INTO alerts (alert_id, voyage_id, tick, sim_hours, code,"
                    " severity, message, advisory, latitude, longitude) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (alert.alert_id, state.voyage_id, alert.tick, alert.sim_hours, alert.code,
                     alert.severity, alert.message, alert.advisory, alert.latitude, alert.longitude),
                )

    def load(self, voyage_id: str) -> Optional[VoyageState]:
        engine = self._engines.get(voyage_id)
        if engine is not None:
            return engine.state
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM voyages WHERE voyage_id = ?", (voyage_id,)
            ).fetchone()
        if row is None:
            return None
        return VoyageState.model_validate_json(row["state_json"])

    def list_voyages(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT voyage_id, created_iso, updated_iso, status, vessel_name, ice_class,
                       origin_name, destination_name, sim_hours, fuel_tonnes, distance_nm
                FROM voyages ORDER BY updated_iso DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            dict(row) | {"is_live": row["voyage_id"] in self._engines} for row in rows
        ]

    def alerts_for(self, voyage_id: str) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE voyage_id = ? ORDER BY sim_hours", (voyage_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, voyage_id: str) -> bool:
        self.drop(voyage_id)
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM voyages WHERE voyage_id = ?", (voyage_id,))
            conn.execute("DELETE FROM ticks WHERE voyage_id = ?", (voyage_id,))
            conn.execute("DELETE FROM alerts WHERE voyage_id = ?", (voyage_id,))
            return cur.rowcount > 0

    def stats(self) -> Dict[str, Any]:
        with self._lock, self._connect() as conn:
            voyages = conn.execute("SELECT COUNT(*) AS n FROM voyages").fetchone()["n"]
            ticks = conn.execute("SELECT COUNT(*) AS n FROM ticks").fetchone()["n"]
            alerts = conn.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()["n"]
        return {
            "database": str(self.db_path),
            "voyages": voyages,
            "ticks": ticks,
            "alerts": alerts,
            "live_engines": len(self._engines),
        }


_STORE: Optional[VoyageStore] = None


def get_store() -> VoyageStore:
    global _STORE
    if _STORE is None:
        _STORE = VoyageStore()
    return _STORE
