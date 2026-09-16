from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


HOUR_MS = 3_600_000
STATE_MAP = {
    "PASS": "ANALYSIS_PASS",
    "WAIT": "ANALYSIS_WAIT",
    "REJECT": "REJECT_ANALYSIS",
}
TERMINAL_STATES = {"EXPIRED", "REJECT_ANALYSIS"}


@dataclass(frozen=True)
class RezRecordResult:
    event_id: int
    event_inserted: bool
    watch_id: int
    previous_state: Optional[str]
    current_state: str
    promoted: bool


def build_watch_key(symbol, side, anchor_timestamp, trigger_level_kind, analysis_version) -> str:
    symbol = str(symbol).strip().upper()
    side = str(side).strip().upper()
    kind = str(trigger_level_kind).strip().upper()
    version = str(analysis_version).strip().upper()
    if not symbol or side not in {"LONG", "SHORT"} or anchor_timestamp is None or not kind or not version:
        raise ValueError("invalid REZ watch identity")
    return f"{symbol}|{side}|{int(anchor_timestamp)}|{kind}|{version}"


def is_promotion(previous_state: Optional[str], current_state: str) -> bool:
    return previous_state == "ANALYSIS_WAIT" and current_state == "ANALYSIS_PASS"


def validate_snapshot_link(current, requested) -> str:
    requested = str(requested).strip()
    if not requested:
        raise ValueError("snapshot id is required")
    if current is None:
        return "SET"
    if str(current) == requested:
        return "NOOP"
    raise ValueError("REZ event already linked to another Shadow snapshot")


class RezWatchStore:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS rez_watch_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_key TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('LONG','SHORT')),
                    analysis_version TEXT NOT NULL,
                    analysis_state TEXT NOT NULL,
                    structure_1h TEXT NOT NULL,
                    trigger_15m TEXT NOT NULL,
                    wait_reason TEXT,
                    protected_swing_timestamp INTEGER NOT NULL,
                    protected_swing_price REAL,
                    trigger_level_kind TEXT NOT NULL,
                    trigger_level_price REAL NOT NULL,
                    first_seen_at_ms INTEGER NOT NULL,
                    last_checked_at_ms INTEGER NOT NULL,
                    last_closed_15m_at_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL,
                    invalidated_at_ms INTEGER
                );

                CREATE TABLE IF NOT EXISTS rez_analysis_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_id INTEGER NOT NULL,
                    shadow_snapshot_id TEXT,
                    created_at_ms INTEGER NOT NULL,
                    structure_1h TEXT NOT NULL,
                    trigger_15m TEXT NOT NULL,
                    analysis_state TEXT NOT NULL,
                    analysis_reason TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    closed_1h_at_ms INTEGER,
                    closed_15m_at_ms INTEGER NOT NULL,
                    FOREIGN KEY(watch_id) REFERENCES rez_watch_state(id) ON DELETE CASCADE,
                    UNIQUE(watch_id, closed_15m_at_ms, analysis_state, trigger_15m)
                );

                CREATE INDEX IF NOT EXISTS idx_rez_watch_state ON rez_watch_state(analysis_state);
                CREATE INDEX IF NOT EXISTS idx_rez_watch_expiry ON rez_watch_state(expires_at_ms);
                CREATE INDEX IF NOT EXISTS idx_rez_event_snapshot ON rez_analysis_events(shadow_snapshot_id);
                """
            )

    def table_names(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {str(row["name"]) for row in rows}

    def get_watch(self, watch_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM rez_watch_state WHERE id = ?", (int(watch_id),)).fetchone()
        return dict(row) if row else None

    def get_event(self, event_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM rez_analysis_events WHERE id = ?", (int(event_id),)).fetchone()
        return dict(row) if row else None

    def record_analysis(
        self,
        *,
        symbol: str,
        side: str,
        provider: str,
        result,
        now_ms: int,
        ttl_hours: int,
    ) -> RezRecordResult:
        raw_state = str(getattr(result, "state", "")).upper()
        if raw_state not in STATE_MAP:
            raise ValueError("invalid REZ analysis state")
        closed_15m = getattr(result, "closed_15m_at_ms", None)
        if closed_15m is None:
            raise ValueError("closed 15m timestamp is required for REZ persistence")
        ttl_hours = int(ttl_hours)
        if ttl_hours <= 0:
            raise ValueError("ttl_hours must be positive")
        now_ms = int(now_ms)
        side = str(side).upper()
        provider = str(provider).strip().upper()
        if not provider:
            raise ValueError("provider is required")

        watch_key = build_watch_key(
            symbol,
            side,
            getattr(result, "protected_swing_timestamp", None),
            getattr(result, "trigger_level_kind", None),
            getattr(result, "analysis_version", ""),
        )
        desired_state = STATE_MAP[raw_state]
        reason = str(getattr(result, "reason", ""))
        structure = str(getattr(result, "structure_1h", "UNKNOWN")).upper()
        trigger = str(getattr(result, "trigger_15m", "NO_TRIGGER")).upper()
        version = str(getattr(result, "analysis_version", "REZ_V1")).upper()
        protected_price = getattr(result, "protected_swing_price", None)
        trigger_price = getattr(result, "trigger_level_price", None)
        if trigger_price is None:
            raise ValueError("trigger level price is required")
        closed_1h = getattr(result, "closed_1h_at_ms", None)

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM rez_watch_state WHERE watch_key = ?",
                (watch_key,),
            ).fetchone()
            previous_state = str(row["analysis_state"]) if row else None

            if row is None:
                expires_at_ms = now_ms + ttl_hours * HOUR_MS
                invalidated_at = now_ms if desired_state == "REJECT_ANALYSIS" else None
                cursor = conn.execute(
                    """
                    INSERT INTO rez_watch_state (
                        watch_key, symbol, side, analysis_version, analysis_state,
                        structure_1h, trigger_15m, wait_reason,
                        protected_swing_timestamp, protected_swing_price,
                        trigger_level_kind, trigger_level_price,
                        first_seen_at_ms, last_checked_at_ms, last_closed_15m_at_ms,
                        expires_at_ms, invalidated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        watch_key, str(symbol).upper(), side, version, desired_state,
                        structure, trigger, reason if desired_state == "ANALYSIS_WAIT" else None,
                        int(getattr(result, "protected_swing_timestamp")),
                        None if protected_price is None else float(protected_price),
                        str(getattr(result, "trigger_level_kind")).upper(), float(trigger_price),
                        now_ms, now_ms, int(closed_15m), expires_at_ms, invalidated_at,
                    ),
                )
                watch_id = int(cursor.lastrowid)
                current_state = desired_state
            else:
                watch_id = int(row["id"])
                if previous_state in TERMINAL_STATES:
                    current_state = previous_state
                elif previous_state == "ANALYSIS_PASS" and desired_state == "ANALYSIS_WAIT":
                    current_state = previous_state
                else:
                    current_state = desired_state
                invalidated_at = row["invalidated_at_ms"]
                if current_state == "REJECT_ANALYSIS" and invalidated_at is None:
                    invalidated_at = now_ms
                conn.execute(
                    """
                    UPDATE rez_watch_state
                    SET analysis_state = ?, structure_1h = ?, trigger_15m = ?, wait_reason = ?,
                        protected_swing_price = ?, trigger_level_price = ?,
                        last_checked_at_ms = ?, last_closed_15m_at_ms = ?, invalidated_at_ms = ?
                    WHERE id = ?
                    """,
                    (
                        current_state, structure, trigger,
                        reason if current_state == "ANALYSIS_WAIT" else None,
                        None if protected_price is None else float(protected_price),
                        float(trigger_price), now_ms, int(closed_15m), invalidated_at, watch_id,
                    ),
                )

            event_state = current_state
            event_id: Optional[int] = None
            event_inserted = False
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO rez_analysis_events (
                        watch_id, created_at_ms, structure_1h, trigger_15m, analysis_state,
                        analysis_reason, provider, closed_1h_at_ms, closed_15m_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        watch_id, now_ms, structure, trigger, event_state, reason, provider,
                        None if closed_1h is None else int(closed_1h), int(closed_15m),
                    ),
                )
                event_id = int(cursor.lastrowid)
                event_inserted = True
            except sqlite3.IntegrityError:
                existing = conn.execute(
                    """
                    SELECT id FROM rez_analysis_events
                    WHERE watch_id = ? AND closed_15m_at_ms = ? AND analysis_state = ? AND trigger_15m = ?
                    """,
                    (watch_id, int(closed_15m), event_state, trigger),
                ).fetchone()
                if existing is None:
                    raise
                event_id = int(existing["id"])

        return RezRecordResult(
            event_id=int(event_id),
            event_inserted=event_inserted,
            watch_id=watch_id,
            previous_state=previous_state,
            current_state=current_state,
            promoted=is_promotion(previous_state, current_state),
        )

    def expire_due(self, now_ms: int) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE rez_watch_state
                SET analysis_state = 'EXPIRED', last_checked_at_ms = ?
                WHERE analysis_state = 'ANALYSIS_WAIT'
                  AND invalidated_at_ms IS NULL
                  AND expires_at_ms <= ?
                """,
                (int(now_ms), int(now_ms)),
            )
            return int(cursor.rowcount)

    def link_event_snapshot(self, event_id: int, snapshot_id: str) -> None:
        snapshot_id = str(snapshot_id).strip()
        if not snapshot_id:
            raise ValueError("snapshot id is required")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT shadow_snapshot_id FROM rez_analysis_events WHERE id = ?",
                (int(event_id),),
            ).fetchone()
            if row is None:
                raise ValueError("REZ event not found")
            action = validate_snapshot_link(row["shadow_snapshot_id"], snapshot_id)
            if action == "SET":
                conn.execute(
                    "UPDATE rez_analysis_events SET shadow_snapshot_id = ? WHERE id = ?",
                    (snapshot_id, int(event_id)),
                )
