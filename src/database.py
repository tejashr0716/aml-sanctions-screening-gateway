import json
import sqlite3
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import aiosqlite
from src.config import settings
from src.matcher import normalize_string, compute_soundex


class DatabaseManager:
    """Manages SQLite database connections and schemas with WAL mode."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or settings.DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def init_sync_db(self):
        """Initialize SQLite database schema synchronously."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            
            # Entities table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    primary_name TEXT NOT NULL,
                    primary_name_norm TEXT NOT NULL,
                    aliases TEXT,
                    soundex TEXT,
                    un_ref TEXT,
                    nationality TEXT,
                    listed_on TEXT,
                    remarks TEXT
                );
            """)

            # Aliases table for normalized lookups
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entity_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    alias_name TEXT NOT NULL,
                    alias_norm TEXT NOT NULL,
                    soundex TEXT NOT NULL,
                    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
                );
            """)

            # Audit logs table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    query_name TEXT NOT NULL,
                    is_flagged INTEGER NOT NULL,
                    match_rule TEXT NOT NULL,
                    highest_score REAL NOT NULL,
                    matched_entity_id TEXT,
                    matched_entity_name TEXT
                );
            """)

            # Sync metadata table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_timestamp TEXT NOT NULL,
                    total_individuals INTEGER NOT NULL,
                    total_entities INTEGER NOT NULL,
                    source_url TEXT NOT NULL
                );
            """)

            # Indexes for fast screening
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_norm ON entities(primary_name_norm);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_soundex ON entities(soundex);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_aliases_norm ON entity_aliases(alias_norm);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_aliases_soundex ON entity_aliases(soundex);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);")
            conn.commit()

    @asynccontextmanager
    async def get_connection(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        try:
            yield conn
        finally:
            await conn.close()

    async def insert_entities_batch(self, entities: List[Dict[str, Any]], clear_existing: bool = True):
        """Insert or replace entities and their aliases in batch."""
        async with self.get_connection() as conn:
            if clear_existing:
                await conn.execute("DELETE FROM entity_aliases;")
                await conn.execute("DELETE FROM entities;")

            for entity in entities:
                norm_name = normalize_string(entity["primary_name"])
                soundex_code = compute_soundex(entity["primary_name"])
                aliases_json = json.dumps(entity.get("aliases", []))

                await conn.execute("""
                    INSERT OR REPLACE INTO entities 
                    (id, entity_type, primary_name, primary_name_norm, aliases, soundex, un_ref, nationality, listed_on, remarks)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entity["id"],
                    entity["entity_type"],
                    entity["primary_name"],
                    norm_name,
                    aliases_json,
                    soundex_code,
                    entity.get("un_reference_num", ""),
                    entity.get("nationality", ""),
                    entity.get("listed_on", ""),
                    entity.get("remarks", "")
                ))

                for alias in entity.get("aliases", []):
                    alias_norm = normalize_string(alias)
                    alias_soundex = compute_soundex(alias)
                    await conn.execute("""
                        INSERT INTO entity_aliases (entity_id, alias_name, alias_norm, soundex)
                        VALUES (?, ?, ?, ?)
                    """, (entity["id"], alias, alias_norm, alias_soundex))

            await conn.commit()

    async def record_audit_log(
        self,
        request_id: str,
        query_name: str,
        is_flagged: bool,
        match_rule: str,
        highest_score: float,
        matched_entity_id: Optional[str] = None,
        matched_entity_name: Optional[str] = None
    ) -> int:
        """Write an immutable audit log entry."""
        ts = datetime.now(timezone.utc).isoformat()
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                INSERT INTO audit_logs 
                (request_id, timestamp, query_name, is_flagged, match_rule, highest_score, matched_entity_id, matched_entity_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                request_id,
                ts,
                query_name,
                1 if is_flagged else 0,
                match_rule,
                highest_score,
                matched_entity_id,
                matched_entity_name
            ))
            await conn.commit()
            return cursor.lastrowid

    async def get_audit_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent audit logs."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_total_entities_count(self) -> int:
        """Get total count of indexed entities."""
        async with self.get_connection() as conn:
            cursor = await conn.execute("SELECT COUNT(*) as count FROM entities;")
            row = await cursor.fetchone()
            return row["count"] if row else 0

    async def record_sync_metadata(self, total_ind: int, total_ent: int, source_url: str):
        """Record sync metadata."""
        ts = datetime.now(timezone.utc).isoformat()
        async with self.get_connection() as conn:
            await conn.execute("""
                INSERT INTO sync_metadata (sync_timestamp, total_individuals, total_entities, source_url)
                VALUES (?, ?, ?, ?)
            """, (ts, total_ind, total_ent, source_url))
            await conn.commit()

    async def get_last_sync_timestamp(self) -> Optional[str]:
        """Get last sync timestamp."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT sync_timestamp FROM sync_metadata ORDER BY id DESC LIMIT 1;"
            )
            row = await cursor.fetchone()
            return row["sync_timestamp"] if row else None


db = DatabaseManager()
