"""
DevMesh Storage Layer
---------------------
SQLite-based persistence for tasks, agents, projects, and audit logs.
Replaces the flat-file memory.json system.
"""

import sqlite3
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

log = logging.getLogger("devmesh.storage")

class StorageManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not self._conn:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            # Better concurrency and resilience for multi-agent writes.
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self):
        """Initialize database schema."""
        conn = self._get_conn()
        cur = conn.cursor()
        
        # Agents table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                model_id TEXT PRIMARY KEY,
                session_id TEXT,
                role TEXT,
                status TEXT,
                is_active INTEGER DEFAULT 1,
                connected_at TEXT,
                last_seen TEXT,
                hardware_usage JSON
            )
        """)

        # Tasks table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                description TEXT,
                status TEXT,
                owner_model TEXT,
                working_dir TEXT,
                file_target TEXT,
                created_at TEXT,
                completed_at TEXT,
                result_summary TEXT,
                details JSON
            )
        """)

        # Projects table (New in Phase 1 upgrade)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                name TEXT,
                folder TEXT,
                base_dir TEXT,
                created_at TEXT,
                last_used_at TEXT
            )
        """)

        # Audit Log table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                event_type TEXT,
                model_id TEXT,
                details JSON
            )
        """)

        # KV Store for global state (config, rulebook version, etc.)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value JSON
            )
        """)

        # Context RAG tables (Phase 3 foundation)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS context_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT,
                value TEXT,
                source_agent TEXT,
                confidence_score REAL,
                timestamp TEXT,
                project_id TEXT
            )
        """)

        # Performance indexes for frequent lookups.
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_agents_last_seen ON agents(last_seen DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_context_items_timestamp ON context_items(timestamp DESC)")

        conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Agent Methods ────────────────────────────────────────────────────────

    def upsert_agent(self, model_id: str, data: Dict):
        conn = self._get_conn()
        existing = self.get_agent(model_id)
        if existing:
            # Only update fields provided in data
            final_data = {**existing, **data}
        else:
            final_data = data
        
        conn.execute("""
            INSERT OR REPLACE INTO agents (
                model_id, session_id, role, status, is_active, 
                connected_at, last_seen, hardware_usage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            model_id,
            final_data.get("session_id"),
            final_data.get("role", "agent"),
            final_data.get("status", "idle"),
            final_data.get("is_active", 1),
            final_data.get("connected_at", existing["connected_at"] if existing else datetime.now().isoformat()),
            datetime.now().isoformat(),
            json.dumps(final_data.get("hardware_usage", {}))
        ))
        conn.commit()

    def get_agent(self, model_id: str) -> Optional[Dict]:
        cur = self._get_conn().cursor()
        cur.execute("SELECT * FROM agents WHERE model_id = ?", (model_id,))
        row = cur.fetchone()
        if row:
            d = dict(row)
            if d.get("hardware_usage"):
                d["hardware_usage"] = json.loads(d["hardware_usage"])
            return d
        return None

    def get_all_agents(self) -> List[Dict]:
        cur = self._get_conn().cursor()
        cur.execute("SELECT * FROM agents")
        agents = []
        for row in cur.fetchall():
            d = dict(row)
            if d.get("hardware_usage"):
                d["hardware_usage"] = json.loads(d["hardware_usage"])
            agents.append(d)
        return agents

    # ── Task Methods ─────────────────────────────────────────────────────────

    def upsert_task(self, task_id: str, data: Dict):
        conn = self._get_conn()
        existing = self.get_task(task_id)
        if existing:
            final_data = {**existing, **data}
        else:
            final_data = data

        conn.execute("""
            INSERT OR REPLACE INTO tasks (
                task_id, description, status, owner_model, working_dir, 
                file_target, created_at, completed_at, result_summary, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            final_data.get("description", ""),
            final_data.get("status", "queued"),
            final_data.get("owner_model"),
            final_data.get("working_dir", ""),
            final_data.get("file_target", ""),
            final_data.get("created_at", existing["created_at"] if existing else datetime.now().isoformat()),
            final_data.get("completed_at"),
            final_data.get("result_summary"),
            json.dumps(final_data.get("details", {}))
        ))
        conn.commit()

    def get_task(self, task_id: str) -> Optional[Dict]:
        cur = self._get_conn().cursor()
        cur.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = cur.fetchone()
        if row:
            d = dict(row)
            if d.get("details"):
                d["details"] = json.loads(d["details"])
            return d
        return None

    def get_recent_tasks(self, limit: int = 50) -> List[Dict]:
        cur = self._get_conn().cursor()
        cur.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))
        tasks = []
        for row in cur.fetchall():
            d = dict(row)
            if d.get("details"):
                d["details"] = json.loads(d["details"])
            tasks.append(d)
        return tasks

    # ── Project Methods ──────────────────────────────────────────────────────

    def upsert_project(self, project_id: str, data: Dict):
        conn = self._get_conn()
        existing = self.get_project(project_id)
        if existing:
            final_data = {**existing, **data}
        else:
            final_data = data

        conn.execute("""
            INSERT OR REPLACE INTO projects (project_id, name, folder, base_dir, created_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            final_data.get("name", ""),
            final_data.get("folder", ""),
            final_data.get("base_dir", ""),
            final_data.get("created_at", existing["created_at"] if existing else datetime.now().isoformat()),
            datetime.now().isoformat()
        ))
        conn.commit()

    def get_project(self, project_id: str) -> Optional[Dict]:
        cur = self._get_conn().cursor()
        cur.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_projects_for_dir(self, base_dir: str) -> List[Dict]:
        cur = self._get_conn().cursor()
        cur.execute("SELECT * FROM projects WHERE base_dir = ?", (base_dir,))
        return [dict(row) for row in cur.fetchall()]

    # ── Audit & Event Methods ────────────────────────────────────────────────

    def log_event(self, event_type: str, model_id: str, details: Dict):
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO audit_log (timestamp, event_type, model_id, details)
            VALUES (?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            event_type,
            model_id,
            json.dumps(details)
        ))
        conn.commit()

    def get_recent_events(self, limit: int = 100) -> List[Dict]:
        cur = self._get_conn().cursor()
        cur.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        events = []
        for row in cur.fetchall():
            d = dict(row)
            if d.get("details"):
                d["details"] = json.loads(d["details"])
            events.append(d)
        return events

    # ── Context RAG Methods (Phase 3) ────────────────────────────────────────

    def add_context_item(self, key: str, value: str, source_agent: str, confidence: float = 1.0, project_id: str = None):
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO context_items (key, value, source_agent, confidence_score, timestamp, project_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (key, value, source_agent, confidence, datetime.now().isoformat(), project_id))
        conn.commit()

    def search_context(self, query: str, limit: int = 10) -> List[Dict]:
        cur = self._get_conn().cursor()
        # Simple LIKE-based keyword search for now
        cur.execute("""
            SELECT * FROM context_items 
            WHERE key LIKE ? OR value LIKE ? 
            ORDER BY timestamp DESC LIMIT ?
        """, (f"%{query}%", f"%{query}%", limit))
        return [dict(row) for row in cur.fetchall()]

    def get_all_context(self, limit: int = 50) -> List[Dict]:
        cur = self._get_conn().cursor()
        cur.execute("SELECT * FROM context_items ORDER BY timestamp DESC LIMIT ?", (limit,))
        return [dict(row) for row in cur.fetchall()]
