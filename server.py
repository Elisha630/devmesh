"""
DevMesh v3.0 — Local Multi-Agent Orchestration Server
------------------------------------------------------
Single entry point. Run this one file and:
  - WebSocket coordinator starts on ws://127.0.0.1:7700  (AI agents connect here)
  - Dashboard WebSocket starts on ws://127.0.0.1:7702    (browser connects here)
  - HTTP dashboard serves on    http://127.0.0.1:7701    (opens in browser automatically)
  - Installed AI CLIs are detected and listed in the dashboard
  - Tasks are broadcast from the browser chat to all connected agents
"""

import asyncio
import json
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Dict, List, Optional, Set, Any
from enum import Enum

import websockets

from config import get_server_config, KNOWN_CLI_TOOLS, TOOL_PROFILES
from logger import setup_logging
from errors import ToolInvokeError
from storage import StorageManager

cfg = get_server_config()
log = setup_logging(log_level=cfg.log_level, log_file=cfg.log_file)


class ReusableHTTPServer(HTTPServer):
    """HTTPServer with SO_REUSEADDR to allow quick restarts."""
    allow_reuse_address = True
    
    def server_bind(self):
        """Override to set SO_REUSEADDR socket option."""
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()

# ── Domain models ──────────────────────────────────────────────────────────

class TaskState(Enum):
    QUEUED    = "queued"
    CLAIMED   = "claimed"
    WORKING   = "working"
    PAUSED    = "paused"
    COMPLETED = "completed"
    FAILED    = "failed"
    ABANDONED = "abandoned"


class LockType(Enum):
    READ     = "read"
    WRITE    = "write"
    INTENT   = "intent"
    CO_WRITE = "co_write"


RULEBOOK = {
    "version": "3.0",
    "updated_at": "2026-03-20",
}


@dataclass
class AgentInfo:
    model: str
    version: Optional[str]
    capabilities: Dict
    role: str
    websocket_id: int
    session_id: Optional[str] = None
    connected_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now().isoformat())
    resource_request: Dict = field(default_factory=dict)
    status: str = "idle"
    current_task: Optional[str] = None


@dataclass
class LockInfo:
    target: str
    lock_type: LockType
    holder: str
    acquired_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_heartbeat: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class TaskInfo:
    task_id: str
    description: str
    file: str
    operation: str
    working_dir: str = "/tmp"
    priority: int = 1
    status: TaskState = TaskState.QUEUED
    owner_model: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    critic_required: bool = False
    critic_model: Optional[str] = None
    created_by: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    claimed_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class ContextBufferEntry:
    file_path: str
    content: str
    version: int = 0
    last_updated: float = field(default_factory=time.time)
    last_writer: Optional[str] = None
    diffs: List[str] = field(default_factory=list)


class HardwareThrottle:
    def __init__(self, max_vram: float, max_ram: float):
        self.max_vram = max_vram
        self.max_ram  = max_ram
        self.used_vram = 0.0
        self.used_ram  = 0.0
        self.allocations: Dict[str, Dict] = {}

    def allocate(self, model: str, req: Dict) -> bool:
        # If re-allocated (e.g., agent reconnect), avoid double counting.
        if model in self.allocations:
            self.release(model)
        v = req.get("vram_gb", 0)
        r = req.get("ram_gb", 0)
        if self.used_vram + v > self.max_vram or self.used_ram + r > self.max_ram:
            return False
        self.used_vram += v
        self.used_ram  += r
        self.allocations[model] = {"vram": v, "ram": r}
        return True

    def release(self, model: str):
        if model in self.allocations:
            a = self.allocations.pop(model)
            self.used_vram -= a["vram"]
            self.used_ram  -= a["ram"]

    def status(self) -> Dict:
        return {
            "vram": {"used": round(self.used_vram, 2), "total": self.max_vram},
            "ram":  {"used": round(self.used_ram, 2), "total": self.max_ram},
        }


def detect_installed_tools():
    """Return list of AI CLI tools found in PATH."""
    found = []
    for tool in KNOWN_CLI_TOOLS:
        path = shutil.which(tool["cmd"])
        if path:
            try:
                result = subprocess.run(
                    [tool["cmd"], "--version"],
                    capture_output=True, text=True, timeout=cfg.ai_cli_version_timeout_sec
                )
                version = (result.stdout or result.stderr or "").strip().split("\n")[0][:60]
            except Exception:
                version = "installed"
            found.append({**tool, "path": path, "version": version, "status": "detected"})
    return found


# ── Server ─────────────────────────────────────────────────────────────────

class DevMeshServer:
    def __init__(self):
        self.agent_clients: Set     = set()
        self.dash_clients: Set      = set()
        self.agents: Dict[str, AgentInfo]         = {}
        self.locks:  Dict[str, List[LockInfo]]    = {}
        self.tasks:  Dict[str, TaskInfo]          = {}
        self.ctx:    Dict[str, ContextBufferEntry] = {}
        self.architect: Optional[str]             = None
        self._ws_counter = 0
        self.hw = HardwareThrottle(cfg.gpu_vram_gb, cfg.ram_gb)
        self.file_subs: Dict[str, Set[str]] = {}
        self.chat_log:  List[Dict]          = []
        self.event_log: List[Dict]          = []
        # Keep a rolling history for the dashboard.
        self.hw_history: List[Dict] = []
        self._hw_sample_task: Optional[asyncio.Task] = None

        # Agent disconnect grace: if an agent drops, we pause its tasks for this long.
        self._agent_disconnect_deadline: Dict[str, float] = {}

        # Guard against infinite conflict-resolution loops per (file) hot path.
        self._conflict_resolve_guard: Dict[str, float] = {}
        self.detected_tools: List[Dict]     = detect_installed_tools()
        self.launched_procs: Dict[str, subprocess.Popen] = {}
        self._agent_stderr_paths: Dict[str, str] = {}  # Track stderr log files
        self.http_server: Optional[HTTPServer] = None
        
        # ✅ FIX 5: Throttle full state pushes to prevent excessive serialization
        self._last_full_state_push: float = 0.0
        self._full_state_push_interval: float = 0.5  # milliseconds between full state pushes
        
        # New Storage Layer
        db_path = cfg.audit_log_dir / "devmesh.db"
        self.storage = StorageManager(db_path, audit_log_path=cfg.audit_log_path)
        
        # Migrate legacy memory.json if exists
        self._migrate_legacy_memory()
        
        # ✅ FIX 1: Clear any agents left over from a previous run
        self._reset_stale_agents()

        # Framework gate state for the most recent dashboard task.
        # Only after framework becomes READY do we broadcast task execution.
        self.framework: Dict = {"status": "idle"}
        log.info(f"Initialized DevMesh server with {len(self.detected_tools)} detected tools")
        log.info(f"Hardware: GPU {cfg.gpu_vram_gb}GB VRAM, {cfg.ram_gb}GB RAM")
        log.info(f"Persistence: SQLite at {db_path}")

    def _migrate_legacy_memory(self):
        legacy_path = cfg.audit_log_dir / "memory.json"
        if legacy_path.exists():
            log.info("Migrating legacy memory.json to SQLite...")
            try:
                with open(legacy_path, "r") as f:
                    mem = json.load(f)
                
                # Migrate projects
                for base_dir, projs in mem.get("projects", {}).items():
                    for p in projs:
                        self.storage.upsert_project(p.get("id", f"mig_{int(time.time())}"), {
                            "name": p.get("name"),
                            "folder": p.get("folder"),
                            "base_dir": base_dir,
                            "created_at": p.get("created_at"),
                            "last_used_at": p.get("last_used_at")
                        })
                
                # Migrate agents metadata
                for model, data in mem.get("agents", {}).items():
                    self.storage.upsert_agent(model, {
                        "status": "offline",
                        "last_seen": data.get("last_seen")
                    })

                # Rename old file instead of deleting
                legacy_path.rename(legacy_path.with_suffix(".json.bak"))
                log.info("Migration complete.")
            except Exception as e:
                log.error(f"Migration failed: {e}")

    def _reset_stale_agents(self):
        """On fresh start, mark all persisted agents as inactive so they don't appear as connected."""
        try:
            with self.storage._get_conn() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE agents SET is_active = 0, status = 'offline'")
                conn.commit()
            log.info("Reset all stale agents to inactive on startup.")
        except Exception as e:
            log.warning(f"Failed to reset stale agents: {e}")

    # ── Internal helpers ──────────────────────────────────────────────────

    def _agent_roster(self) -> Dict:
        """Small snapshot of connected agents so agents can coordinate."""
        return {
            "architect": self.architect,
            "agents": [
                {
                    "model": a.model,
                    "role": a.role,
                    "status": a.status,
                    "current_task": a.current_task,
                }
                for a in self.agents.values()
            ],
        }

    async def _broadcast_roster(self):
        """Tell all agents who's connected (coordination signal)."""
        await self._broadcast_agents({
            "event": "agent_roster",
            "roster": self._agent_roster(),
        })

    async def _send_to_agent(self, model: str, payload: Dict):
        """Send a payload to one agent by model id."""
        if model not in self.agents:
            return
        target_id = self.agents[model].websocket_id
        msg = json.dumps(payload)
        for ws in list(self.agent_clients):
            if getattr(ws, "_agent_id", None) == target_id:
                try:
                    await ws.send(msg)
                except Exception:
                    pass
                break

    def _normalize_task_text(self, text: str) -> str:
        """Cheap normalization so similar prompts compare well."""
        return " ".join(text.lower().strip().split())

    def _select_or_create_project_folder(self, base_dir: str, task_text: str) -> str:
        """
        Given a user-selected working_dir and a new task description, either:
        - Reuse an existing project folder for similar tasks in that base_dir, or
        - Create a new subfolder and register it in memory.
        """
        projects_for_dir = self.storage.get_projects_for_dir(base_dir)

        norm_text = self._normalize_task_text(task_text)

        # Try to match an existing project by simple text similarity.
        best_match = None
        best_score = 0.0
        for p in projects_for_dir:
            name = p.get("name") or ""
            norm_name = self._normalize_task_text(name)
            if not norm_name:
                continue
            # Very simple similarity: Jaccard over word sets.
            a = set(norm_text.split())
            b = set(norm_name.split())
            inter = len(a & b)
            union = max(len(a | b), 1)
            score = inter / union
            if score > best_score:
                best_score = score
                best_match = p

        # If reasonably similar, reuse existing project folder.
        if best_match and best_score >= 0.6 and best_match.get("folder"):
            self.storage.upsert_project(best_match["project_id"], {"last_used_at": datetime.now().isoformat()})
            return best_match["folder"]

        # Otherwise create a new folder for this project.
        base = Path(base_dir)
        slug = "_".join(norm_text.split()[:4]) or "project"
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)
        idx = len(projects_for_dir) + 1
        folder_name = f"{slug}_{idx:02d}"
        project_path = base / folder_name
        try:
            project_path.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Fallback to base_dir if mkdir fails.
            return base_dir

        project_id = f"proj_{int(time.time())}"
        self.storage.upsert_project(project_id, {
            "name": task_text,
            "folder": str(project_path),
            "base_dir": base_dir,
            "created_at": datetime.now().isoformat(),
        })
        return str(project_path)

    def _audit(self, ev: Dict):
        model_id = ev.get("model") or ev.get("by") or ev.get("owner_model") or "server"
        event_type = ev.get("event", "unknown")
        self.storage.log_event(event_type, model_id, ev)
        
        # Also log to event log for UI
        ev["timestamp"] = datetime.now().isoformat()
        self.event_log.append(ev)
        if len(self.event_log) > 500:
            self.event_log = self.event_log[-500:]

    def _ts(self):
        return datetime.now().isoformat()

    def _serialize_task(self, t: TaskInfo) -> Dict:
        return {
            "task_id": t.task_id, "description": t.description,
            "file": t.file, "operation": t.operation,
            "working_dir": t.working_dir,
            "priority": t.priority, "status": t.status.value,
            "owner_model": t.owner_model, "depends_on": t.depends_on,
            "required_capabilities": t.required_capabilities,
            "critic_required": t.critic_required, "critic_model": t.critic_model,
            "created_by": t.created_by, "created_at": t.created_at,
            "claimed_at": t.claimed_at, "completed_at": t.completed_at,
        }

    def _full_state(self) -> Dict:
        # Merge active agents with persistent agent data
        all_agents = self.storage.get_all_agents()
        agent_map = {}
        
        # First add agents from storage (including inactive ones for history)
        for a in all_agents:
            agent_map[a["model_id"]] = a
        
        # Overlay in-memory agents (active connections)
        for model, info in self.agents.items():
            agent_map[model] = {
                "model_id": model, 
                "role": info.role, 
                "status": info.status,
                "current_task": info.current_task, 
                "connected_at": info.connected_at,
                "is_active": 1,
            }
        
        # Filter to only include active agents (is_active: 1)
        active_agents = {k: v for k, v in agent_map.items() if v.get("is_active") == 1}

        # Get recent tasks from storage
        db_tasks = self.storage.get_recent_tasks(100)
        task_map = {t["task_id"]: t for t in db_tasks}
        # Overlay in-memory tasks (for very recent/pending ones)
        for tid, info in self.tasks.items():
            task_map[tid] = self._serialize_task(info)

        return {
            "type": "state",
            "agents": active_agents,
            "tasks":  task_map,
            "locks":  {t: [{"holder": l.holder, "type": l.lock_type.value} for l in ls]
                       for t, ls in self.locks.items()},
            "hardware":      self.hw.status(),
            "hardware_history": self.hw_history,
            "detected_tools": self.detected_tools,
            "memory": {"context": self.storage.get_all_context(20)},
            "chat_log":      self.chat_log[-100:],
            "event_log":     self.event_log[-100:],
        }

    async def _broadcast_agents(self, payload: Dict):
        """Send to all AI agent WebSocket connections."""
        if not self.agent_clients:
            return
        msg = json.dumps(payload)
        await asyncio.gather(*[c.send(msg) for c in self.agent_clients], return_exceptions=True)
        # Add to event log and push to dashboard
        ev = dict(payload)
        ev.setdefault("timestamp", self._ts())
        self.event_log.append(ev)
        if len(self.event_log) > 500:
            self.event_log = self.event_log[-500:]
        asyncio.create_task(self._push_dash({"type": "event", "data": ev}))

    async def _push_dash(self, payload: Dict):
        """Send to all browser dashboard connections."""
        if not self.dash_clients:
            return
        msg = json.dumps(payload)
        await asyncio.gather(*[c.send(msg) for c in self.dash_clients], return_exceptions=True)

    async def _push_dash_throttled(self, payload: Dict):
        """Push to dashboard with throttling for full state updates to avoid serialization overhead.
        
        If payload contains a full state (_full_state result), throttle to ~500ms intervals.
        Other payloads go through immediately.
        """
        if not self.dash_clients:
            return
        
        # Check if this is a full state push (has 'agents', 'tasks', 'locks' keys)
        is_full_state = "agents" in payload and "tasks" in payload and "locks" in payload
        
        if is_full_state:
            now = time.time()
            if now - self._last_full_state_push >= self._full_state_push_interval:
                self._last_full_state_push = now
                await self._push_dash(payload)
            # else: silently throttle this full state push
        else:
            # Non-full-state payloads always go through
            await self._push_dash(payload)

    # ── Agent protocol handlers ───────────────────────────────────────────

    async def _register(self, ws, data: Dict) -> Dict:
        model = data.get("model", "unknown")
        session_id = data.get("session_id")
        
        # Check if this is a reconnection
        existing_agent = self.storage.get_agent(model)
        is_reconnect = False
        if existing_agent and session_id and existing_agent.get("session_id") == session_id:
            log.info(f"Agent {model} reconnecting with session {session_id}")
            is_reconnect = True
        
        if is_reconnect and existing_agent:
            role = existing_agent.get("role", "agent")
        else:
            role = "architect" if self.architect is None else "agent"
            if role == "architect":
                self.architect = model

        self._ws_counter += 1
        agent = AgentInfo(
            model=model, version=data.get("version"),
            capabilities=data.get("capabilities", {}),
            role=role, websocket_id=self._ws_counter,
            resource_request=data.get("resources", {}),
            session_id=session_id
        )
        self.agents[model] = agent
        ws._agent_id = self._ws_counter

        # If it's a reconnect, restore state
        if is_reconnect:
            # Cancel any pending disconnect expiry.
            self._agent_disconnect_deadline.pop(model, None)

            # If we already reserved hardware for this model during the grace window,
            # don't double-allocate.
            if model not in self.hw.allocations:
                self.hw.allocate(model, agent.resource_request)

            # Resume any paused tasks.
            for t in self.tasks.values():
                if t.owner_model == model and t.status == TaskState.PAUSED:
                    t.status = TaskState.WORKING
                    self.storage.upsert_task(t.task_id, {"status": t.status.value})

            # Derive status/current_task from locks if possible.
            current_task = None
            for target, locks in self.locks.items():
                if any(l.holder == model for l in locks):
                    current_task = target
                    break
            agent.current_task = current_task
            if current_task:
                held_lock = None
                for l in self.locks.get(current_task, []):
                    if l.holder == model:
                        held_lock = l
                        break
                if held_lock and held_lock.lock_type == LockType.READ:
                    agent.status = "reading"
                elif held_lock and held_lock.lock_type == LockType.WRITE:
                    agent.status = "writing"
                else:
                    agent.status = "working"
            else:
                prev_status = existing_agent.get("status", "idle")
                # If the agent was previously marked disconnected/offline, treat it as idle on reconnect.
                if str(prev_status).lower() in {"disconnected", "offline"}:
                    agent.status = "idle"
                else:
                    agent.status = prev_status
        else:
            if not self.hw.allocate(model, agent.resource_request):
                agent.status = "suspended"
            else:
                agent.status = "idle"
            if not session_id:
                session_id = str(uuid.uuid4())
                agent.session_id = session_id

        # Persist agent registration
        self.storage.upsert_agent(model, {
            "session_id": session_id,
            "role": role,
            "status": agent.status,
            "is_active": 1,
            "connected_at": agent.connected_at,
            "hardware_usage": agent.resource_request
        })

        await self._broadcast_agents({"event": "agent_registered", "model": model,
                                       "role": role, "status": agent.status, "time": time.time()})
        asyncio.create_task(self._broadcast_roster())
        asyncio.create_task(self._push_dash(self._full_state()))
        self._audit({"event": "register", "model": model, "role": role, "reconnect": is_reconnect})
        
        return {"event": "registered", "model": model, "role": role, "session_id": session_id,
                "rulebook": RULEBOOK, 
                "memory": {
                    "agents": self.storage.get_all_agents(), 
                    "recent_tasks": self.storage.get_recent_tasks(20),
                    "context": self.storage.get_all_context(20)
                },
                "roster": self._agent_roster(),
                "hardware_status": self.hw.status()}

    def _lock_conflict(self, target: str, lt: LockType, requester: str) -> bool:
        existing = self.locks.get(target, [])
        if not existing:
            return False
        if lt == LockType.READ:
            return any(l.lock_type == LockType.WRITE for l in existing)
        if lt == LockType.INTENT:
            return any(l.lock_type in {LockType.INTENT, LockType.WRITE}
                       and l.holder != requester for l in existing)
        if lt == LockType.WRITE:
            return any(l.holder != requester for l in existing)
        if lt == LockType.CO_WRITE:
            return any(l.lock_type != LockType.CO_WRITE for l in existing)
        return True

    async def _lock_request(self, data: Dict) -> Dict:
        model, target = data.get("model", "?"), data.get("target")
        try:
            lt = LockType(data.get("type", "read"))
        except ValueError:
            return {"event": "lock_denied", "reason": "invalid_lock_type", "target": target}
        if not target:
            return {"event": "lock_denied", "reason": "no_target"}
        if model not in self.agents or self.agents[model].status == "suspended":
            return {"event": "lock_denied", "reason": "agent_suspended", "target": target}
        if self._lock_conflict(target, lt, model):
            return {"event": "lock_denied", "target": target, "retry_after_ms": 2000}

        self.locks.setdefault(target, []).append(LockInfo(target=target, lock_type=lt, holder=model))
        if lt in {LockType.READ, LockType.WRITE}:
            self.agents[model].status = "reading" if lt == LockType.READ else "writing"
            self.agents[model].current_task = target

        await self._broadcast_agents({"event": "lock_granted", "model": model,
                                       "target": target, "type": lt.value})
        self._audit({"event": "lock_granted", "model": model, "target": target, "type": lt.value})
        asyncio.create_task(self._push_dash(self._full_state()))
        return {"event": "lock_granted", "target": target, "type": lt.value}

    async def _lock_release(self, data: Dict) -> Dict:
        model, target = data.get("model", "?"), data.get("target")
        if not target:
            return {"event": "lock_release_ack", "ok": False}
        self.locks[target] = [l for l in self.locks.get(target, []) if l.holder != model]
        if not self.locks.get(target):
            self.locks.pop(target, None)
        if model in self.agents:
            self.agents[model].status = "idle"
            self.agents[model].current_task = None

        await self._broadcast_agents({"event": "lock_released", "model": model, "target": target})
        self._audit({"event": "lock_released", "model": model, "target": target})
        asyncio.create_task(self._push_dash_throttled(self._full_state()))
        return {"event": "lock_release_ack", "ok": True}

    async def _file_change(self, data: Dict) -> Dict:
        model, path = data.get("model"), data.get("path")
        content, diff = data.get("content", ""), data.get("diff")
        stdout, stderr = data.get("stdout", ""), data.get("stderr", "")
        operation = data.get("operation", "write")

        entry = self.ctx.get(path) or ContextBufferEntry(file_path=path, content=content)
        
        # Conflict Detection (Phase 4)
        conflict_detected = False
        if entry.last_writer and entry.last_writer != model:
            # If someone else wrote within the last 5 seconds
            if time.time() - entry.last_updated < 5.0:
                previous_writer = entry.last_writer
                log.warning(f"Conflict detected on {path} between {model} and {entry.last_writer}")
                conflict_detected = True
                self._audit({"event": "conflict_detected", "path": path, "agents": [model, previous_writer]})

                # Lightweight diff arbitration scaffolding: ask a critic agent to re-write the artifact.
                # Note: the current AgentBridge always writes an "output artifact"; to support true
                # arbitration, we pass `target_file` and let the bridge overwrite that path.
                guard_ts = self._conflict_resolve_guard.get(path)
                now_ts = time.time()
                if not guard_ts or (now_ts - guard_ts) > cfg.conflict_resolve_cooldown_sec:
                    self._conflict_resolve_guard[path] = now_ts

                    critic_model = None
                    if self.architect and self.architect not in {model, previous_writer}:
                        critic_model = self.architect
                    else:
                        for m in self.agents.keys():
                            if m not in {model, previous_writer}:
                                critic_model = m
                                break

                    if critic_model:
                        prev_content = entry.content[:4000] if entry.content else ""
                        prev_diffs = entry.diffs[-5:] if entry.diffs else []
                        new_diff = diff[:4000] if diff else ""
                        resolve_text = (
                            "You are the conflict resolution/critic agent.\n"
                            f"Resolve write conflict for file: {path}\n"
                            f"Participants: {previous_writer} vs {model}\n\n"
                            "Previous writer artifact snapshot (truncated):\n"
                            f"{prev_content}\n\n"
                            "Previous diffs (last few, truncated):\n"
                            +("\n".join(prev_diffs)[-6000:] if prev_diffs else "(no prior diffs)") + "\n\n"
                            "New incoming diff (truncated):\n"
                            f"{new_diff}\n\n"
                            "Output requirements:\n"
                            "- Produce the best merged artifact content for the entire file.\n"
                            f"- Overwrite the target file exactly at: {path}\n"
                            "- Prefer correctness and completeness over minimality.\n"
                        )
                        working_dir = str(Path(path).parent)
                        await self._send_to_agent(critic_model, {
                            "event": "task_instruction",
                            "text": resolve_text,
                            "working_dir": working_dir,
                            "target_file": path,
                            "conflict": {"between": [previous_writer, model]},
                        })

        entry.version += 1
        entry.last_updated = time.time()
        entry.last_writer = model
        if content: entry.content = content
        if diff: entry.diffs.append(diff)
        self.ctx[path] = entry

        if path in self.file_subs:
            for c in self.agent_clients:
                aid = getattr(c, "_agent_id", None)
                for ag in self.agents.values():
                    if ag.websocket_id == aid and ag.model in self.file_subs[path]:
                        await c.send(json.dumps({
                            "event": "file_changed", "path": path,
                            "operation": operation, "by": model,
                            "version": entry.version,
                            "conflict": conflict_detected
                        }))
        
        self._audit({
            "event": "file_changed",
            "model": model,
            "path": path,
            "operation": operation,
            "stdout": str(stdout)[:20000] if stdout else "",
            "stderr": str(stderr)[:20000] if stderr else "",
        })
        asyncio.create_task(self._push_dash_throttled(self._full_state()))
        return {
            "event": "file_change_ack",
            "path": path,
            "version": entry.version,
            "conflict": conflict_detected,
        }

    async def _task_event(self, data: Dict) -> Dict:
        ev, task_id, model = data.get("event"), data.get("task_id"), data.get("model")

        if ev == "create":
            if not task_id or task_id in self.tasks:
                return {"event": "error", "reason": "invalid_or_duplicate_task_id"}
            t = TaskInfo(
                task_id=task_id, description=data.get("description", ""),
                file=data.get("file", ""), operation=data.get("operation", "create"),
                priority=data.get("priority", 1), depends_on=data.get("depends_on", []),
                required_capabilities=data.get("required_capabilities", []),
                critic_required=data.get("critic_required", False),
                created_by=model or "dashboard",
            )
            self.tasks[task_id] = t
            
            # Persist task
            self.storage.upsert_task(task_id, {
                "description": t.description,
                "status": t.status.value,
                "owner_model": t.owner_model,
                "working_dir": t.working_dir,
                "file_target": t.file,
                "created_at": t.created_at
            })

            self._audit({"event": "task_created", "task_id": task_id, "by": model})
            await self._broadcast_agents({"event": "task_created", "task": self._serialize_task(t)})
            asyncio.create_task(self._push_dash_throttled(self._full_state()))
            return {"event": "task_created_ack", "task_id": task_id}

        if ev == "claim":
            t = self.tasks.get(task_id)
            if not t:
                return {"event": "error", "reason": "task_not_found"}
            if t.status != TaskState.QUEUED or t.owner_model:
                return {"event": "claim_denied", "reason": "not_available"}
            
            deps_ok = all(
                dep in self.tasks and self.tasks[dep].status == TaskState.COMPLETED
                for dep in t.depends_on
            )
            if not deps_ok:
                return {"event": "claim_denied", "reason": "dependency_not_ready"}
            
            t.owner_model = model
            t.status = TaskState.CLAIMED
            t.claimed_at = datetime.now().isoformat()
            
            # Persist update
            self.storage.upsert_task(task_id, {
                "owner_model": model,
                "status": t.status.value,
                "claimed_at": t.claimed_at
            })

            self._audit({"event": "task_claimed", "task_id": task_id, "by": model})
            await self._broadcast_agents({"event": "task_claimed", "task_id": task_id, "by": model})
            asyncio.create_task(self._push_dash_throttled(self._full_state()))
            return {"event": "claim_ack", "task_id": task_id}

        if ev == "start":
            t = self.tasks.get(task_id)
            if not t or t.owner_model != model or t.status != TaskState.CLAIMED:
                return {"event": "start_denied"}
            t.status = TaskState.WORKING
            
            self.storage.upsert_task(task_id, {"status": t.status.value})

            self._audit({"event": "task_started", "task_id": task_id, "by": model})
            await self._broadcast_agents({"event": "task_started", "task_id": task_id})
            asyncio.create_task(self._push_dash(self._full_state()))
            return {"event": "start_ack", "task_id": task_id}

        if ev == "complete":
            t = self.tasks.get(task_id)
            if not t:
                return {"event": "error", "reason": "task_not_found"}
            approved_by = data.get("approved_by")
            if t.critic_required:
                if not approved_by or approved_by == t.owner_model or approved_by not in self.agents:
                    return {"event": "complete_denied", "reason": "critic_required"}
                t.critic_model = approved_by
            
            t.status = TaskState.COMPLETED
            t.completed_at = datetime.now().isoformat()
            
            self.storage.upsert_task(task_id, {
                "status": t.status.value,
                "completed_at": t.completed_at,
                "result_summary": data.get("summary", "")
            })

            self._audit({"event": "task_completed", "task_id": task_id})
            await self._broadcast_agents({"event": "task_completed", "task_id": task_id})
            asyncio.create_task(self._push_dash(self._full_state()))
            return {"event": "complete_ack", "task_id": task_id}

        if ev == "abandon":
            t = self.tasks.get(task_id)
            if not t:
                return {"event": "error", "reason": "task_not_found"}
            t.status = TaskState.ABANDONED
            t.owner_model = None
            
            self.storage.upsert_task(task_id, {"status": t.status.value, "owner_model": None})

            self._audit({"event": "task_abandoned", "task_id": task_id})
            await self._broadcast_agents({"event": "task_abandoned", "task_id": task_id})
            asyncio.create_task(self._push_dash(self._full_state()))
            return {"event": "abandon_ack", "task_id": task_id}

        return {"event": "error", "reason": "unknown_task_event"}

    async def _bid(self, data: Dict) -> Dict:
        task_id, model = data.get("task_id"), data.get("model")
        t = self.tasks.get(task_id)
        if not t:
            return {"event": "error", "reason": "task_not_found"}
        if t.status != TaskState.QUEUED or t.owner_model:
            return {"event": "bid_denied"}
        deps_ok = all(dep in self.tasks and self.tasks[dep].status == TaskState.COMPLETED
                      for dep in t.depends_on)
        if not deps_ok:
            return {"event": "bid_denied", "reason": "dependency_not_ready"}

        # Simplified award
        best = model
        t.owner_model = best
        t.status = TaskState.CLAIMED
        t.claimed_at = datetime.now().isoformat()
        
        self.storage.upsert_task(task_id, {
            "owner_model": best,
            "status": t.status.value,
            "claimed_at": t.claimed_at
        })

        self._audit({"event": "task_awarded", "task_id": task_id, "to": best})
        await self._broadcast_agents({"event": "task_awarded", "task_id": task_id, "to": best})
        asyncio.create_task(self._push_dash(self._full_state()))
        return {"event": "bid_awarded", "task_id": task_id, "to": best}

    # ── Dispatch ──────────────────────────────────────────────────────────

    async def _handle_agent_message(self, ws, message: str):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            await ws.send(json.dumps({"event": "error", "reason": "invalid_json"}))
            return

        ev = data.get("event", "")
        if   ev == "register":      r = await self._register(ws, data)
        elif ev == "lock_request":  r = await self._lock_request(data)
        elif ev == "lock_release":  r = await self._lock_release(data)
        elif ev == "file_change":   r = await self._file_change(data)
        elif ev in {"create_task","claim_task","start_task","complete_task","abandon_task"}:
            data["event"] = ev.replace("_task", "")
            r = await self._task_event(data)
        elif ev == "bid_task":      r = await self._bid(data)
        elif ev == "heartbeat":
            m = data.get("model")
            ts_iso = datetime.now().isoformat()
            if m in self.agents:
                self.agents[m].last_seen = ts_iso
                self.storage.upsert_agent(m, {"status": self.agents[m].status, "last_seen": ts_iso})
            
            tgt = data.get("target")
            if tgt and tgt in self.locks:
                for l in self.locks[tgt]:
                    if l.holder == m:
                        l.last_heartbeat = ts_iso
            r = {"event": "heartbeat_ack"}
        elif ev == "subscribe_file":
            fp = data.get("path")
            if fp: self.file_subs.setdefault(fp, set()).add(data.get("model"))
            r = {"event": "subscribe_ack", "path": fp}
        elif ev == "framework_ready":
            model = data.get("model")
            overview = data.get("overview", "")
            project_dir = data.get("working_dir") or data.get("project_dir") or self.framework.get("project_dir")
            task_text = data.get("task_text") or self.framework.get("task_text")

            # Record framework and broadcast to all agents.
            self.framework = {
                "status": "ready",
                "by": model,
                "task_text": task_text,
                "project_dir": project_dir,
                "overview": overview,
                "timestamp": self._ts(),
            }
            self._audit({"event": "framework_ready", "model": model, "working_dir": project_dir})
            await self._broadcast_agents({
                "event": "framework_ready",
                "model": model,
                "working_dir": project_dir,
                "overview": overview,
                "task_text": task_text,
            })

            # Now that framework is ready, broadcast the actual execution instruction.
            if task_text and project_dir:
                await self._broadcast_agents({
                    "event": "task_instruction",
                    "text": task_text,
                    "working_dir": project_dir,
                    "framework_overview": overview,
                    "from": "framework_gate",
                    "timestamp": self._ts(),
                })
                self._audit({"event": "dashboard_task", "text": task_text, "working_dir": project_dir})

            asyncio.create_task(self._push_dash(self._full_state()))
            r = {"event": "framework_ack"}

        elif ev == "framework_patch":
            model = data.get("model")
            patch_text = data.get("patch", "")
            new_overview = data.get("overview", "")
            if self.framework.get("status") != "ready":
                return await ws.send(json.dumps({"event": "framework_patch_denied", "reason": "not_ready"}))

            if new_overview:
                self.framework["overview"] = new_overview
            if patch_text:
                self.framework.setdefault("patches", []).append({
                    "by": model,
                    "patch": patch_text,
                    "timestamp": self._ts(),
                })
            self.framework["last_edited_by"] = model
            self.framework["last_edited_at"] = self._ts()

            self._audit({"event": "framework_patched", "model": model, "working_dir": self.framework.get("project_dir")})
            await self._broadcast_agents({
                "event": "framework_patched",
                "model": model,
                "working_dir": self.framework.get("project_dir"),
                "overview": self.framework.get("overview", ""),
                "patch": patch_text,
            })
            asyncio.create_task(self._push_dash(self._full_state()))
            r = {"event": "framework_patch_ack"}
        elif ev == "share_context":
            m, k, v = data.get("model"), data.get("key"), data.get("value")
            if k and v:
                self.storage.add_context_item(k, v, m, data.get("confidence", 1.0))
                self._audit({"event": "context_shared", "model": m, "key": k})
                r = {"event": "share_context_ack", "ok": True}
            else:
                r = {"event": "error", "reason": "missing_key_or_value"}
        elif ev == "query_context":
            q = data.get("query", "")
            query_id = data.get("query_id")
            results = self.storage.search_context(q)
            r = {"event": "context_results", "query_id": query_id, "query": q, "results": results}
        elif ev == "get_status":
            r = {"event": "status",
                 "agents": {k: {"role": v.role, "status": v.status} for k, v in self.agents.items()},
                 "tasks":  {k: self._serialize_task(v) for k, v in self.tasks.items()},
                 "hardware": self.hw.status()}
        else:
            r = {"event": "error", "reason": f"unknown_event:{ev}"}

        await ws.send(json.dumps(r))

    # ── Dashboard command handler (from browser) ──────────────────────────

    async def _handle_dash_message(self, data: Dict):
        t = data.get("type")

        if t == "chat":
            text = data.get("text", "").strip()
            working_dir = data.get("working_dir", "/tmp").strip()
            if not text:
                return
            # Validate working directory
            try:
                wd_path = Path(working_dir)
                if not wd_path.exists():
                    log.warning(f"Working dir does not exist: {working_dir}")
                    reply = {"sender": "system",
                             "text": f"⚠ Working directory not found: {working_dir}. Using /tmp instead.",
                             "timestamp": self._ts()}
                    self.chat_log.append(reply)
                    await self._push_dash({"type": "chat_message", "data": reply})
                    working_dir = "/tmp"
            except Exception as e:
                log.warning(f"Invalid working dir: {working_dir} - {e}")
                working_dir = "/tmp"

            project_dir = self._select_or_create_project_folder(working_dir, text)

            entry = {"sender": "user", "text": text, "working_dir": working_dir, "timestamp": self._ts()}
            self.chat_log.append(entry)

            self.framework = {
                "status": "pending",
                "task_text": text,
                "project_dir": project_dir,
                "base_dir": working_dir,
                "timestamp": self._ts(),
            }
            self._audit({"event": "framework_pending", "working_dir": project_dir, "text": text})

            await self._broadcast_agents({
                "event": "framework_pending",
                "working_dir": project_dir,
                "task_text": text,
                "from": "dashboard",
                "timestamp": entry["timestamp"],
            })

            if self.architect:
                await self._send_to_agent(self.architect, {
                    "event": "framework_request",
                    "task_text": text,
                    "working_dir": project_dir,
                    "timestamp": entry["timestamp"],
                })

            await self._push_dash({"type": "chat_message", "data": entry})
            
            # ✅ FIX 4: Check for agents and provide appropriate feedback
            if not self.agents:
                # No agents connected — tell user clearly
                reply = {"sender": "system",
                         "text": f"⚠ No agents connected. Connect an agent first, then send the task.",
                         "timestamp": self._ts()}
            else:
                n = len(self.agents)
                reply = {"sender": "system",
                         "text": f"Framework gate started for {n} agent{'s' if n!=1 else ''} in {project_dir}",
                         "timestamp": self._ts()}
                # ✅ FIX 4: If no architect to build the framework, broadcast directly to all agents
                if not self.architect:
                    await self._broadcast_agents({
                        "event": "task_instruction",
                        "text": text,
                        "working_dir": project_dir,
                        "from": "dashboard_direct",
                        "timestamp": entry["timestamp"],
                    })
            self.chat_log.append(reply)
            await self._push_dash({"type": "chat_message", "data": reply})

        elif t == "get_state":
            await self._push_dash(self._full_state())

        elif t == "create_task":
            data["event"] = "create"
            data["model"] = "dashboard"
            r = await self._task_event(data)
            await self._push_dash({"type": "task_ack", "data": r})

        elif t == "rescan_tools":
            self.detected_tools = detect_installed_tools()
            await self._push_dash(self._full_state())

        elif t == "launch_agent":
            tool_name = data.get("tool_name")
            result = await self._launch_agent(tool_name)
            await self._push_dash({"type": "launch_result", "data": result})

        elif t == "stop_agent":
            tool_name = data.get("tool_name")
            result = self._stop_agent(tool_name)
            # ✅ FIX 2b: Immediately remove matching agents — skip reconnect grace
            for model in list(self.agents.keys()):
                if model == tool_name or model.startswith(tool_name):
                    # Bypass grace window: delete immediately
                    self._agent_disconnect_deadline.pop(model, None)
                    self.hw.release(model)
                    del self.agents[model]
                    if self.architect == model:
                        self.architect = None
                    self.storage.upsert_agent(model, {"is_active": 0, "status": "offline"})
                    self._audit({"event": "agent_stopped", "model": model})
            await self._push_dash({"type": "stop_result", "data": result})
            await self._push_dash(self._full_state())

    # ── Agent launcher ───────────────────────────────────────────────────

    async def _launch_agent(self, tool_name: str) -> Dict:
        bridge = Path(__file__).parent / "agent_bridge.py"
        if not bridge.exists():
            return {"ok": False, "error": "agent_bridge.py not found next to server.py"}

        tool = next((t for t in self.detected_tools if t["name"] == tool_name), None)
        if not tool:
            return {"ok": False, "error": f"Tool '{tool_name}' not detected"}

        if tool_name in self.launched_procs:
            proc = self.launched_procs[tool_name]
            if proc.poll() is None:
                return {"ok": False, "error": f"{tool_name} bridge already running (pid {proc.pid})"}

        try:
            # Capture stderr to diagnose launch failures
            stderr_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=f'_{tool_name}.log')
            stderr_path = stderr_file.name
            stderr_file.close()
            
            proc = subprocess.Popen(
                [sys.executable, str(bridge), "--tool", tool_name,
                 "--ws", cfg.ws_url],
                stdout=subprocess.DEVNULL, 
                stderr=open(stderr_path, 'w'),
                preexec_fn=None,
            )
            self.launched_procs[tool_name] = proc
            
            # Store stderr path so we can check it later
            if not hasattr(self, '_agent_stderr_paths'):
                self._agent_stderr_paths = {}
            self._agent_stderr_paths[tool_name] = stderr_path
            
            msg = f"Launched {tool['label']} bridge (pid {proc.pid})"
            self._audit({"event": "agent_launched", "tool": tool_name, "pid": proc.pid})
            entry = {"sender": "system", "text": msg, "timestamp": self._ts()}
            self.chat_log.append(entry)
            await self._push_dash({"type": "chat_message", "data": entry})
            log.info(f"Launched {tool_name} agent bridge (pid {proc.pid})")
            return {"ok": True, "msg": msg}
        except Exception as e:
            log.error(f"Failed to launch {tool_name}: {e}")
            return {"ok": False, "error": str(e)}

    def _stop_agent(self, tool_name: str) -> Dict:
        proc = self.launched_procs.get(tool_name)
        if not proc:
            return {"ok": False, "error": "No bridge running for that tool"}
        
        # ✅ FIX 3.1: SIGTERM with escalation to SIGKILL
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log.warning(f"Agent {tool_name} did not exit on SIGTERM, sending SIGKILL")
            proc.kill()
        
        del self.launched_procs[tool_name]
        return {"ok": True, "msg": f"Stopped {tool_name} bridge"}

    # ── WebSocket connection handlers ─────────────────────────────────────

    async def agent_handler(self, ws):
        self.agent_clients.add(ws)
        try:
            async for msg in ws:
                await self._handle_agent_message(ws, msg)
        except websockets.exceptions.ConnectionClosed:
            # Expected during disconnects/reconnects; don't spam logs/tracebacks.
            pass
        except Exception as e:
            log.error(f"Error in agent handler for {getattr(ws, '_agent_id', 'unknown')}: {e}")
        finally:
            self.agent_clients.discard(ws)
            aid = getattr(ws, "_agent_id", None)
            for model, ag in list(self.agents.items()):
                if ag.websocket_id == aid:
                    self._drop_agent(model, reason="disconnect")
                    break

    async def dash_handler(self, ws, path=""):
        self.dash_clients.add(ws)
        try:
            await ws.send(json.dumps(self._full_state()))
            async for msg in ws:
                try:
                    await self._handle_dash_message(json.loads(msg))
                except Exception as e:
                    log.error(f"Error processing dashboard message: {e}")
        except (websockets.exceptions.ConnectionClosed, ConnectionResetError):
            # Normal disconnect/reset; avoid "connection handler failed" tracebacks.
            pass
        finally:
            self.dash_clients.discard(ws)

    async def _monitor_launched_agents(self):
        """Monitor launched agent processes and report errors if they crash."""
        while True:
            await asyncio.sleep(2)  # Check every 2 seconds
            for tool_name in list(self.launched_procs.keys()):
                proc = self.launched_procs[tool_name]
                if proc.poll() is not None:  # Process has exited
                    # Read stderr to see why it failed
                    stderr_path = getattr(self, '_agent_stderr_paths', {}).get(tool_name)
                    error_msg = "Agent process terminated unexpectedly"
                    if stderr_path:
                        try:
                            with open(stderr_path, 'r') as f:
                                stderr_content = f.read().strip()
                                if stderr_content:
                                    # Find the most recent error line
                                    lines = stderr_content.split('\n')
                                    error_msg = lines[-1] if lines else error_msg
                            # Clean up temp file
                            Path(stderr_path).unlink(missing_ok=True)
                        except Exception:
                            pass
                    
                    # Report to dashboard
                    entry = {
                        "sender": "system",
                        "text": f"⚠ {tool_name} bridge failed: {error_msg}",
                        "timestamp": self._ts()
                    }
                    self.chat_log.append(entry)
                    await self._push_dash({"type": "chat_message", "data": entry})
                    log.error(f"Agent {tool_name} process crashed: {error_msg}")
                    
                    # Clean up
                    del self.launched_procs[tool_name]
                    if tool_name in getattr(self, '_agent_stderr_paths', {}):
                        del self._agent_stderr_paths[tool_name]

    # ── Background: stale lock cleanup ────────────────────────────────────

    async def _cleanup(self):
        while True:
            now_iso = datetime.now().isoformat()
            now_ts = datetime.now().timestamp()
            expired = []
            for target, locks in list(self.locks.items()):
                for l in locks:
                    # Convert l.last_heartbeat (ISO string) back to timestamp for comparison
                    try:
                        lb_ts = datetime.fromisoformat(l.last_heartbeat).timestamp()
                        if now_ts - lb_ts > cfg.lock_ttl_sec + cfg.heartbeat_grace_sec:
                            # During disconnect grace, keep locks/tasks reserved.
                            deadline = self._agent_disconnect_deadline.get(l.holder)
                            if deadline and now_ts < deadline:
                                continue
                            expired.append(l)
                    except Exception:
                        expired.append(l) # invalid timestamp format

                self.locks[target] = [l for l in locks if l not in expired]
                if not self.locks[target]:
                    self.locks.pop(target, None)
            
            for l in expired:
                # Already filtered by grace window above; this lock is truly expired.
                log.warning(f"Lock expired for {l.holder} on {l.target} (heartbeat timeout)")
                for t in self.tasks.values():
                    if t.owner_model == l.holder and t.status in {TaskState.WORKING, TaskState.PAUSED}:
                        t.status = TaskState.ABANDONED
                        t.owner_model = None
                        self.storage.upsert_task(t.task_id, {"status": t.status.value, "owner_model": None})
                        log.warning(f"Task {t.task_id} abandoned due to heartbeat timeout")
                        self._audit({"event": "task_abandoned", "task_id": t.task_id,
                                     "reason": "heartbeat_timeout"})
                await self._broadcast_agents({"event": "lock_dropped", "model": l.holder,
                                               "target": l.target, "reason": "heartbeat_timeout"})
                self._audit({"event": "lock_dropped", "model": l.holder, "target": l.target})
            await asyncio.sleep(2)

    async def _hardware_sampler(self):
        """Periodically sample hardware usage for dashboard heatmap."""
        while True:
            st = self.hw.status()
            self.hw_history.append({
                "ts": self._ts(),
                "vram_used": st["vram"]["used"],
                "vram_total": st["vram"]["total"],
                "ram_used": st["ram"]["used"],
                "ram_total": st["ram"]["total"],
            })
            if len(self.hw_history) > cfg.hardware_history_len:
                self.hw_history = self.hw_history[-cfg.hardware_history_len:]
            # Keep dashboard data fresh even if no other events occur.
            if self.dash_clients:
                await self._push_dash(self._full_state())
            await asyncio.sleep(cfg.hardware_sample_interval_sec)

    def _drop_agent(self, model: str, reason: str = "disconnect"):
        """Handle agent disconnects with a reconnect grace window."""
        # If we already have a pending expiry, don't schedule again.
        if model in self._agent_disconnect_deadline:
            return

        deadline = time.time() + cfg.agent_reconnect_grace_sec
        self._agent_disconnect_deadline[model] = deadline

        # Mark in-memory agent status as disconnected, but keep locks/tasks reserved.
        if model in self.agents:
            self.agents[model].status = "disconnected"

        # Persist agent as inactive during the grace window.
        self.storage.upsert_agent(model, {"is_active": 0, "status": "disconnected"})

        # Pause any in-flight tasks for this agent (keep owner_model so the agent can resume).
        for t in self.tasks.values():
            if t.owner_model == model and t.status in {TaskState.CLAIMED, TaskState.WORKING, TaskState.PAUSED}:
                t.status = TaskState.PAUSED
                self.storage.upsert_task(t.task_id, {"status": t.status.value, "owner_model": model})
                self._audit({"event": "task_paused", "task_id": t.task_id, "reason": reason})

        self._audit({"event": "agent_dropped", "model": model, "reason": reason})
        asyncio.create_task(self._broadcast_roster())
        asyncio.create_task(self._push_dash(self._full_state()))

        # After grace expires, abandon tasks and release locks/hardware.
        asyncio.create_task(self._expire_agent_disconnect(model=model, deadline=deadline, reason=reason))

    async def _expire_agent_disconnect(self, model: str, deadline: float, reason: str):
        await asyncio.sleep(max(0.0, deadline - time.time()))

        # If the agent reconnected (and we removed/rescheduled the deadline), do nothing.
        if self._agent_disconnect_deadline.get(model) != deadline:
            return

        # Expiry complete, clear deadline marker.
        self._agent_disconnect_deadline.pop(model, None)

        # Release resources/locks and abandon tasks.
        self.hw.release(model)

        if model in self.agents:
            del self.agents[model]
        if self.architect == model:
            self.architect = None

        released_targets = []
        for target, locks in list(self.locks.items()):
            self.locks[target] = [l for l in locks if l.holder != model]
            if len(locks) != len(self.locks[target]):
                released_targets.append(target)
            if not self.locks[target]:
                self.locks.pop(target, None)

        # Abandon paused/working tasks for this agent.
        for t in self.tasks.values():
            if t.owner_model == model and t.status in {TaskState.CLAIMED, TaskState.WORKING, TaskState.PAUSED}:
                t.status = TaskState.ABANDONED
                t.owner_model = None
                self.storage.upsert_task(t.task_id, {"status": t.status.value, "owner_model": None})
                self._audit({"event": "task_abandoned", "task_id": t.task_id, "reason": "reconnect_grace_timeout"})

        # Mark agent as inactive in storage after grace expires.
        self.storage.upsert_agent(model, {"is_active": 0, "status": "disconnected"})

        for target in released_targets:
            asyncio.create_task(self._broadcast_agents({
                "event": "lock_dropped",
                "model": model,
                "target": target,
                "reason": "reconnect_grace_timeout",
            }))

        asyncio.create_task(self._broadcast_roster())
        asyncio.create_task(self._push_dash(self._full_state()))

    def _shutdown_launched_agents(self):
        for tool_name, proc in list(self.launched_procs.items()):
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            self.launched_procs.pop(tool_name, None)

    # ── Main ──────────────────────────────────────────────────────────────

    async def run(self):
        agent_ws = websockets.serve(self.agent_handler, cfg.ws_host, cfg.ws_port)
        dash_ws  = websockets.serve(self.dash_handler,  cfg.ws_host, cfg.dashboard_port)
        
        dashboard_path = Path(__file__).parent / "dashboard.html"
        if not dashboard_path.exists():
            log.error(f"Dashboard HTML not found at {dashboard_path}")
            raise FileNotFoundError(f"Missing dashboard.html")
        
        try:
            http_server = ReusableHTTPServer((cfg.ws_host, cfg.http_port),
                                            self._make_http_handler(dashboard_path))
            self.http_server = http_server
            http_thread = Thread(target=http_server.serve_forever, daemon=True)
            http_thread.start()
            log.debug(f"HTTP server started on {cfg.ws_host}:{cfg.http_port}")
        except OSError as e:
            log.error(f"Failed to start HTTP server on {cfg.ws_host}:{cfg.http_port}: {e}")
            raise
        
        log.info(f"DevMesh Server Started")
        log.info(f"  Agent WebSocket:     {cfg.ws_url}")
        log.info(f"  Dashboard WebSocket: {cfg.dashboard_ws_url}")
        log.info(f"  HTTP Dashboard:      {cfg.http_url}")
        
        if cfg.auto_open_browser:
            webbrowser.open(cfg.http_url)
        
        async with agent_ws, dash_ws:
            cleanup_task = asyncio.create_task(self._cleanup())
            hw_task = asyncio.create_task(self._hardware_sampler())
            monitor_task = asyncio.create_task(self._monitor_launched_agents())
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
            finally:
                cleanup_task.cancel()
                hw_task.cancel()
                monitor_task.cancel()
                self._shutdown_launched_agents()
                # Gracefully close storage
                self.storage.close()
                if self.http_server:
                    with suppress(KeyboardInterrupt):
                        self.http_server.shutdown()
    
    def _list_folders(self, path: str = "/home") -> List[Dict]:
        entries: List[Dict] = []
        try:
            raw_path = path or "/"
            p = Path(raw_path).expanduser()
            if not p.exists() or not p.is_dir():
                return []
            for item in p.iterdir():
                if item.name.startswith('.'):
                    continue
                try:
                    if item.is_dir():
                        count = None
                        try:
                            count = sum(1 for c in item.iterdir() if not c.name.startswith('.'))
                        except (PermissionError, OSError):
                            count = None
                        entries.append({
                            "name": item.name, "path": str(item), "type": "dir", "count": count,
                        })
                    else:
                        entries.append({
                            "name": item.name, "path": str(item), "type": "file",
                        })
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            return []
        return entries

    def _make_http_handler(self, dashboard_path: Path):
        server = self
        from urllib.parse import urlparse, parse_qs
        class DashboardHandler(BaseHTTPRequestHandler):
            def do_GET(handler):
                if handler.path == "/":
                    handler.send_response(200)
                    handler.send_header("Content-type", "text/html")
                    handler.end_headers()
                    # Read on-demand so dashboard.html edits reflect immediately.
                    html = dashboard_path.read_text()
                    handler.wfile.write(html.encode())
                elif handler.path == "/api/default_workdir":
                    try:
                        handler.send_response(200)
                        handler.send_header("Content-type", "application/json")
                        handler.end_headers()
                        handler.wfile.write(json.dumps({
                            "default_working_dir": str(Path(__file__).parent.resolve())
                        }).encode())
                    except Exception:
                        handler.send_response(500)
                        handler.end_headers()
                elif handler.path.startswith("/api/folders"):
                    try:
                        query = parse_qs(urlparse(handler.path).query)
                        path = query.get("path", [str(Path.home())])[0]
                        entries = server._list_folders(path)
                        handler.send_response(200)
                        handler.send_header("Content-type", "application/json")
                        handler.end_headers()
                        handler.wfile.write(json.dumps({"entries": entries, "path": path}).encode())
                    except Exception as e:
                        log.debug(f"Folder API error: {e}")
                        handler.send_response(500)
                        handler.end_headers()
                else:
                    handler.send_response(404)
                    handler.end_headers()
            def log_message(handler, format, *args):
                pass
        return DashboardHandler

async def main():
    log.info("Starting DevMesh v3.0")
    server = DevMeshServer()
    await server.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
