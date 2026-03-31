"""
DevMesh Domain Models
---------------------
Core dataclasses, enums, and models for the DevMesh system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import time


class TaskState(Enum):
    """Task lifecycle states."""

    QUEUED = "queued"
    CLAIMED = "claimed"
    WORKING = "working"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class LockType(Enum):
    """Types of file/resource locks."""

    READ = "read"
    WRITE = "write"
    INTENT = "intent"
    CO_WRITE = "co_write"


# Global rulebook version
RULEBOOK = {
    "version": "3.0",
    "updated_at": "2026-03-20",
}


@dataclass
class AgentInfo:
    """Represents a connected AI agent."""

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
    """Represents a file/resource lock."""

    target: str
    lock_type: LockType
    holder: str
    acquired_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_heartbeat: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class TaskInfo:
    """Represents a task in the system."""

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
    """Represents a file in the context buffer."""

    file_path: str
    content: str
    version: int = 0
    last_updated: float = field(default_factory=time.time)
    last_writer: Optional[str] = None
    diffs: List[str] = field(default_factory=list)


class HardwareThrottle:
    """Manages GPU VRAM and system RAM allocation."""

    def __init__(self, max_vram: float, max_ram: float):
        self.max_vram = max_vram
        self.max_ram = max_ram
        self.used_vram = 0.0
        self.used_ram = 0.0
        self.allocations: Dict[str, Dict] = {}

    def allocate(self, model: str, req: Dict) -> bool:
        """Attempt to allocate resources for a model."""
        # If re-allocated (e.g., agent reconnect), avoid double counting.
        if model in self.allocations:
            self.release(model)
        v = req.get("vram_gb", 0)
        r = req.get("ram_gb", 0)
        if self.used_vram + v > self.max_vram or self.used_ram + r > self.max_ram:
            return False
        self.used_vram += v
        self.used_ram += r
        self.allocations[model] = {"vram": v, "ram": r}
        return True

    def release(self, model: str) -> None:
        """Release resources allocated to a model."""
        if model in self.allocations:
            a = self.allocations.pop(model)
            self.used_vram -= a["vram"]
            self.used_ram -= a["ram"]

    def status(self) -> Dict:
        """Return current resource usage status."""
        return {
            "vram": {"used": round(self.used_vram, 2), "total": self.max_vram},
            "ram": {"used": round(self.used_ram, 2), "total": self.max_ram},
        }

    def can_allocate(self, req: Dict) -> bool:
        """Check if resources can be allocated without actually allocating."""
        v = req.get("vram_gb", 0)
        r = req.get("ram_gb", 0)
        return self.used_vram + v <= self.max_vram and self.used_ram + r <= self.max_ram


@dataclass
class FrameworkState:
    """Framework state for task execution."""

    status: str = "idle"
    ready: bool = False
    task_id: Optional[str] = None
