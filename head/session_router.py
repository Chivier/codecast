"""
Session Router - manages session state in SQLite.

Maps bot channels to active sessions on remote machines.
Tracks session lifecycle: active → detached → destroyed.
"""

import sqlite3
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Represents an active or detached session."""
    channel_id: str
    machine_id: str
    path: str
    daemon_session_id: str
    sdk_session_id: Optional[str]
    status: str  # active | detached | destroyed
    mode: str  # auto | code | plan | ask
    created_at: str
    updated_at: str


class SessionRouter:
    """SQLite-backed session registry."""

    def __init__(self, db_path: str = "sessions.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database tables."""
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    channel_id TEXT PRIMARY KEY,
                    machine_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    daemon_session_id TEXT NOT NULL,
                    sdk_session_id TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    mode TEXT NOT NULL DEFAULT 'auto',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    machine_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    daemon_session_id TEXT NOT NULL,
                    sdk_session_id TEXT,
                    mode TEXT,
                    created_at TEXT NOT NULL,
                    detached_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_session_log_machine
                ON session_log(machine_id);

                CREATE INDEX IF NOT EXISTS idx_session_log_daemon_id
                ON session_log(daemon_session_id);
            """)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        """Create a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        """Convert a database row to a Session object."""
        return Session(
            channel_id=row["channel_id"],
            machine_id=row["machine_id"],
            path=row["path"],
            daemon_session_id=row["daemon_session_id"],
            sdk_session_id=row["sdk_session_id"],
            status=row["status"],
            mode=row["mode"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def resolve(self, channel_id: str) -> Optional[Session]:
        """Find the active session for a channel."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT * FROM sessions WHERE channel_id = ? AND status = 'active'",
                (channel_id,),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_session(row)
            return None
        finally:
            conn.close()

    def register(
        self,
        channel_id: str,
        machine_id: str,
        path: str,
        daemon_session_id: str,
        mode: str = "auto",
    ) -> None:
        """Register a new active session for a channel."""
        now = datetime.utcnow().isoformat()
        conn = self._connect()
        try:
            # If there's an existing active session on this channel, detach it first
            existing = conn.execute(
                "SELECT * FROM sessions WHERE channel_id = ? AND status = 'active'",
                (channel_id,),
            ).fetchone()

            if existing:
                self._detach_internal(conn, channel_id)

            conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (channel_id, machine_id, path, daemon_session_id, sdk_session_id, status, mode, created_at, updated_at)
                   VALUES (?, ?, ?, ?, NULL, 'active', ?, ?, ?)""",
                (channel_id, machine_id, path, daemon_session_id, mode, now, now),
            )
            conn.commit()
            logger.info(f"Registered session: {channel_id} -> {machine_id}:{path} ({daemon_session_id})")
        finally:
            conn.close()

    def update_sdk_session(self, channel_id: str, sdk_session_id: str) -> None:
        """Update the SDK session ID (obtained from Claude result message)."""
        now = datetime.utcnow().isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE sessions SET sdk_session_id = ?, updated_at = ? WHERE channel_id = ? AND status = 'active'",
                (sdk_session_id, now, channel_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_mode(self, channel_id: str, mode: str) -> None:
        """Update the session mode."""
        now = datetime.utcnow().isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE sessions SET mode = ?, updated_at = ? WHERE channel_id = ? AND status = 'active'",
                (mode, now, channel_id),
            )
            conn.commit()
        finally:
            conn.close()

    def detach(self, channel_id: str) -> Optional[Session]:
        """
        Detach the active session on a channel (don't destroy it).
        Returns the detached session, or None if no active session.
        """
        conn = self._connect()
        try:
            session = self._detach_internal(conn, channel_id)
            conn.commit()
            return session
        finally:
            conn.close()

    def _detach_internal(self, conn: sqlite3.Connection, channel_id: str) -> Optional[Session]:
        """Internal detach (within an existing connection/transaction)."""
        cursor = conn.execute(
            "SELECT * FROM sessions WHERE channel_id = ? AND status = 'active'",
            (channel_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        session = self._row_to_session(row)
        now = datetime.utcnow().isoformat()

        # Move to session log
        conn.execute(
            """INSERT INTO session_log
               (channel_id, machine_id, path, daemon_session_id, sdk_session_id, mode, created_at, detached_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session.channel_id, session.machine_id, session.path,
             session.daemon_session_id, session.sdk_session_id, session.mode,
             session.created_at, now),
        )

        # Update status
        conn.execute(
            "UPDATE sessions SET status = 'detached', updated_at = ? WHERE channel_id = ?",
            (now, channel_id),
        )

        logger.info(f"Detached session: {channel_id} ({session.daemon_session_id})")
        return session

    def destroy(self, channel_id: str) -> Optional[Session]:
        """Mark a session as destroyed."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT * FROM sessions WHERE channel_id = ?",
                (channel_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            session = self._row_to_session(row)
            now = datetime.utcnow().isoformat()

            conn.execute(
                "UPDATE sessions SET status = 'destroyed', updated_at = ? WHERE channel_id = ?",
                (now, channel_id),
            )
            conn.commit()
            logger.info(f"Destroyed session: {channel_id} ({session.daemon_session_id})")
            return session
        finally:
            conn.close()

    def list_sessions(self, machine_id: Optional[str] = None) -> list[Session]:
        """List all sessions, optionally filtered by machine."""
        conn = self._connect()
        try:
            if machine_id:
                cursor = conn.execute(
                    "SELECT * FROM sessions WHERE machine_id = ? ORDER BY updated_at DESC",
                    (machine_id,),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM sessions ORDER BY updated_at DESC"
                )
            return [self._row_to_session(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def list_active_sessions(self) -> list[Session]:
        """List only active sessions."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT * FROM sessions WHERE status = 'active' ORDER BY updated_at DESC"
            )
            return [self._row_to_session(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def find_session_by_daemon_id(self, daemon_session_id: str) -> Optional[Session]:
        """Find a session by its daemon session ID (for resume)."""
        conn = self._connect()
        try:
            # Check active sessions first
            cursor = conn.execute(
                "SELECT * FROM sessions WHERE daemon_session_id = ?",
                (daemon_session_id,),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_session(row)

            # Check session log
            cursor = conn.execute(
                "SELECT * FROM session_log WHERE daemon_session_id = ? ORDER BY detached_at DESC LIMIT 1",
                (daemon_session_id,),
            )
            log_row = cursor.fetchone()
            if log_row:
                return Session(
                    channel_id=log_row["channel_id"],
                    machine_id=log_row["machine_id"],
                    path=log_row["path"],
                    daemon_session_id=log_row["daemon_session_id"],
                    sdk_session_id=log_row["sdk_session_id"],
                    status="detached",
                    mode=log_row["mode"] or "auto",
                    created_at=log_row["created_at"],
                    updated_at=log_row["detached_at"] or log_row["created_at"],
                )
            return None
        finally:
            conn.close()

    def find_sessions_by_machine_path(self, machine_id: str, path: str) -> list[Session]:
        """Find sessions on a specific machine and path."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT * FROM sessions WHERE machine_id = ? AND path = ? ORDER BY updated_at DESC",
                (machine_id, path),
            )
            return [self._row_to_session(row) for row in cursor.fetchall()]
        finally:
            conn.close()
