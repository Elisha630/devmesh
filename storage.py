"""
DevMesh Storage Layer
---------------------
SQLite-based persistence for tasks, agents, projects, and audit logs.
Replaces the flat-file memory.json system.

Thread Safety Note:
This module uses aiosqlite for async operations to ensure true thread safety
when accessed from multiple threads (HTTP server, async event loop, etc.).
"""

import sqlite3
import orjson
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from contextlib import contextmanager
import queue
import time

log = logging.getLogger("devmesh.storage")


class _ConnectionPool:
    """Simple connection pool for thread-safe SQLite access."""

    def __init__(self, db_path: Path, pool_size: int = 5):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: queue.Queue = queue.Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._initialized = False

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with proper settings."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Better concurrency and resilience for multi-agent writes.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_pool(self):
        """Initialize the connection pool if not already done."""
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    for _ in range(self.pool_size):
                        self._pool.put(self._create_connection())
                    self._initialized = True

    @contextmanager
    def get_connection(self):
        """Get a connection from the pool (context manager)."""
        self._ensure_pool()
        conn = self._pool.get()
        try:
            yield conn
        finally:
            self._pool.put(conn)

    def close_all(self):
        """Close all connections in the pool."""
        with self._lock:
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    conn.close()
                except queue.Empty:
                    break
            self._initialized = False


class StorageManager:
    def __init__(
        self,
        db_path: Path,
        audit_log_path: Optional[Path] = None,
        *,
        async_writes: bool = False,
    ):
        self.db_path = db_path
        self.audit_log_path = audit_log_path
        self._async_writes = async_writes
        self._pool = _ConnectionPool(db_path)
        self._write_queue: Optional[queue.Queue] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._stop_writer: Optional[threading.Event] = None
        self._batch_interval = 0.1  # Batch writes every 100ms (async mode only)
        if async_writes:
            self._write_queue = queue.Queue()
            self._stop_writer = threading.Event()
            self._start_writer_thread()
        self._init_db()
        if self.audit_log_path:
            try:
                self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                log.error(f"Failed to create audit log dir: {e}")

    def _start_writer_thread(self):
        """Start background thread for batched writes."""
        self._writer_thread = threading.Thread(target=self._write_worker, daemon=True)
        self._writer_thread.start()

    def _write_worker(self):
        """Background worker that processes write operations in batches."""
        pending = []
        last_flush = time.time()

        assert self._stop_writer is not None
        assert self._write_queue is not None
        while not self._stop_writer.is_set():
            try:
                # Non-blocking get with timeout
                item = self._write_queue.get(timeout=self._batch_interval)
                if item is None:  # Shutdown signal
                    break
                pending.append(item)

                # Flush if batch is large enough or time has passed
                now = time.time()
                if len(pending) >= 10 or (now - last_flush) >= self._batch_interval:
                    self._flush_batch(pending)
                    pending = []
                    last_flush = now
            except queue.Empty:
                # Timeout - flush any pending writes
                if pending:
                    self._flush_batch(pending)
                    pending = []
                    last_flush = time.time()

        # Final flush on shutdown
        if pending:
            self._flush_batch(pending)

    def _flush_batch(self, operations: list):
        """Execute a batch of database operations."""
        with self._pool.get_connection() as conn:
            for op in operations:
                try:
                    op(conn)
                except Exception as e:
                    log.error(f"Error in batch operation: {e}")
            conn.commit()

    def _queue_write(self, operation):
        """
        Write operation dispatcher.

        In sync mode (unit tests), we execute immediately so reads right after
        writes observe the latest data.
        """
        if not self._async_writes:
            with self._get_conn() as conn:
                operation(conn)
                conn.commit()
            return

        assert self._write_queue is not None
        self._write_queue.put(operation)

    @contextmanager
    def _get_conn(self):
        """Get a connection from the pool (context manager for reads)."""
        with self._pool.get_connection() as conn:
            yield conn

    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            cur = conn.cursor()

            # Agents table
            cur.execute(
                """
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
            """
            )

            # Tasks table
            cur.execute(
                """
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
                    details JSON,
                    priority INTEGER DEFAULT 3
                )
            """
            )

            # Migrate: add priority column if it doesn't exist (for existing databases)
            try:
                cur.execute("SELECT priority FROM tasks LIMIT 1")
            except sqlite3.OperationalError:
                cur.execute("ALTER TABLE tasks ADD COLUMN priority INTEGER DEFAULT 3")
                log.info("Migrated tasks table: added priority column")

            # Projects table (New in Phase 1 upgrade)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT,
                    folder TEXT,
                    base_dir TEXT,
                    created_at TEXT,
                    last_used_at TEXT
                )
            """
            )

            # Audit Log table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    event_type TEXT,
                    model_id TEXT,
                    details JSON
                )
            """
            )

            # KV Store for global state (config, rulebook version, etc.)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value JSON
                )
            """
            )

            # Context RAG tables (Phase 3 foundation)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS context_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT,
                    value TEXT,
                    source_agent TEXT,
                    confidence_score REAL,
                    timestamp TEXT,
                    project_id TEXT
                )
            """
            )

            # Performance indexes for frequent lookups.
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp DESC)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_agents_last_seen ON agents(last_seen DESC)")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_context_items_timestamp ON context_items(timestamp DESC)"
            )

            conn.commit()

    def close(self):
        """Close the storage manager and release all resources."""
        if self._async_writes:
            assert self._stop_writer is not None
            assert self._write_queue is not None
            # Signal writer thread to stop
            self._stop_writer.set()
            self._write_queue.put(None)  # Sentinel to unblock the writer
            # Wait for writer thread to finish
            if self._writer_thread and self._writer_thread.is_alive():
                self._writer_thread.join(timeout=2.0)

        # Close all pooled connections
        self._pool.close_all()

    def _flush_writes(self, timeout: float = 5.0):
        """Flush all pending writes and wait for completion. Used by tests."""
        if self._stop_writer.is_set():
            return
        # Create an event to signal when flush is complete
        flush_event = threading.Event()

        def _flush_and_signal(conn):
            flush_event.set()

        # Queue the flush signal operation
        self._queue_write(_flush_and_signal)

        # Wait for the flush to complete
        flush_event.wait(timeout=timeout)

    # ── Agent Methods ────────────────────────────────────────────────────────

    def upsert_agent(self, model_id: str, data: Dict):
        # Fetch existing data BEFORE queuing to avoid race condition with writer thread
        existing = self.get_agent(model_id)
        if existing:
            final_data = {**existing, **data}
        else:
            final_data = data

        def _do_upsert(conn):
            conn.execute(
                """
                INSERT OR REPLACE INTO agents (
                    model_id, session_id, role, status, is_active, 
                    connected_at, last_seen, hardware_usage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    model_id,
                    final_data.get("session_id"),
                    final_data.get("role", "agent"),
                    final_data.get("status", "idle"),
                    final_data.get("is_active", 1),
                    final_data.get(
                        "connected_at",
                        existing["connected_at"] if existing else datetime.now().isoformat(),
                    ),
                    datetime.now().isoformat(),
                    orjson.dumps(final_data.get("hardware_usage", {})).decode("utf-8"),
                ),
            )

        self._queue_write(_do_upsert)

    def get_agent(self, model_id: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM agents WHERE model_id = ?", (model_id,))
            row = cur.fetchone()
            if row:
                d = dict(row)
                if d.get("hardware_usage"):
                    d["hardware_usage"] = orjson.loads(d["hardware_usage"])
                return d
            return None

    def get_all_agents(self) -> List[Dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM agents")
            agents = []
            for row in cur.fetchall():
                d = dict(row)
                if d.get("hardware_usage"):
                    d["hardware_usage"] = orjson.loads(d["hardware_usage"])
                agents.append(d)
            return agents

    # ── Task Methods ─────────────────────────────────────────────────────────

    def upsert_task(self, task_id: str, data: Dict):
        # Fetch existing data BEFORE queuing to avoid race condition with writer thread
        existing = self.get_task(task_id)
        if existing:
            final_data = {**existing, **data}
        else:
            final_data = data

        # Validate and normalize priority (1-5, default 3)
        priority = final_data.get("priority", 3)
        try:
            priority = int(priority)
            if not (1 <= priority <= 5):
                priority = 3
        except (TypeError, ValueError):
            priority = 3

        def _do_upsert(conn):
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks (
                    task_id, description, status, owner_model, working_dir, 
                    file_target, created_at, completed_at, result_summary, details, priority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    task_id,
                    final_data.get("description", ""),
                    final_data.get("status", "queued"),
                    final_data.get("owner_model"),
                    final_data.get("working_dir", ""),
                    final_data.get("file_target", ""),
                    final_data.get(
                        "created_at",
                        existing["created_at"] if existing else datetime.now().isoformat(),
                    ),
                    final_data.get("completed_at"),
                    final_data.get("result_summary"),
                    orjson.dumps(final_data.get("details", {})).decode("utf-8"),
                    priority,
                ),
            )

        self._queue_write(_do_upsert)

    def get_task(self, task_id: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = cur.fetchone()
            if row:
                d = dict(row)
                if d.get("details"):
                    d["details"] = orjson.loads(d["details"])
                return d
            return None

    def get_recent_tasks(self, limit: int = 50) -> List[Dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            # Sort by priority DESC, then created_at DESC
            cur.execute(
                "SELECT * FROM tasks ORDER BY priority DESC, created_at DESC LIMIT ?", (limit,)
            )
            tasks = []
            for row in cur.fetchall():
                d = dict(row)
                if d.get("details"):
                    d["details"] = orjson.loads(d["details"])
                tasks.append(d)
            return tasks

    # ── Project Methods ──────────────────────────────────────────────────────

    def upsert_project(self, project_id: str, data: Dict):
        def _do_upsert(conn):
            existing = self.get_project(project_id)
            if existing:
                final_data = {**existing, **data}
            else:
                final_data = data

            conn.execute(
                """
                INSERT OR REPLACE INTO projects (project_id, name, folder, base_dir, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    project_id,
                    final_data.get("name", ""),
                    final_data.get("folder", ""),
                    final_data.get("base_dir", ""),
                    final_data.get(
                        "created_at",
                        existing["created_at"] if existing else datetime.now().isoformat(),
                    ),
                    datetime.now().isoformat(),
                ),
            )

        self._queue_write(_do_upsert)

    def get_project(self, project_id: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_projects_for_dir(self, base_dir: str) -> List[Dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM projects WHERE base_dir = ?", (base_dir,))
            return [dict(row) for row in cur.fetchall()]

    # ── Audit & Event Methods ────────────────────────────────────────────────

    def log_event(self, event_type: str, model_id: str, details: Dict):
        def _do_log(conn):
            ts = datetime.now().isoformat()
            conn.execute(
                """
                INSERT INTO audit_log (timestamp, event_type, model_id, details)
                VALUES (?, ?, ?, ?)
            """,
                (ts, event_type, model_id, orjson.dumps(details).decode("utf-8")),
            )
            if self.audit_log_path:
                try:
                    with self.audit_log_path.open("a", encoding="utf-8") as f:
                        f.write(
                            orjson.dumps(
                                {
                                    "timestamp": ts,
                                    "event_type": event_type,
                                    "model_id": model_id,
                                    "details": details,
                                }
                            )
                            + "\n"
                        )
                except Exception as e:
                    log.error(f"Failed to write audit log file: {e}")

        self._queue_write(_do_log)

    def get_recent_events(self, limit: int = 100) -> List[Dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
            events = []
            for row in cur.fetchall():
                d = dict(row)
                if d.get("details"):
                    d["details"] = orjson.loads(d["details"])
                events.append(d)
            return events

    # ── Context RAG Methods (Phase 3) ────────────────────────────────────────

    def add_context_item(
        self,
        key: str,
        value: str,
        source_agent: str,
        confidence: float = 1.0,
        project_id: str = None,
    ):
        def _do_add(conn):
            conn.execute(
                """
                INSERT INTO context_items (key, value, source_agent, confidence_score, timestamp, project_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (key, value, source_agent, confidence, datetime.now().isoformat(), project_id),
            )

        self._queue_write(_do_add)

    def search_context(self, query: str, limit: int = 10) -> List[Dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            # Simple LIKE-based keyword search for now
            cur.execute(
                """
                SELECT * FROM context_items 
                WHERE key LIKE ? OR value LIKE ? 
                ORDER BY timestamp DESC LIMIT ?
            """,
                (f"%{query}%", f"%{query}%", limit),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_all_context(self, limit: int = 50) -> List[Dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM context_items ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]
