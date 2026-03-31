"""
Agent Manager Service
----------------------
Manages agent lifecycle, registration, and status for DevMesh.
"""

import uuid
import time
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from models import AgentInfo, HardwareThrottle


class AgentManager:
    """Manages agent connections, registration, and lifecycle."""

    def __init__(self, storage=None, hardware: HardwareThrottle = None):
        self.agents: Dict[str, AgentInfo] = {}
        self.storage = storage
        self.hardware = hardware
        self._websocket_counter = 0
        self._architect: Optional[str] = None
        self._disconnect_deadline: Dict[str, float] = {}
        self._disconnect_grace_sec = 30.0

        # Callbacks
        self._on_agent_registered: Optional[Callable[[str], Any]] = None
        self._on_agent_disconnected: Optional[Callable[[str], Any]] = None
        self._on_agent_reconnected: Optional[Callable[[str], Any]] = None

    def set_callbacks(
        self,
        on_registered: Callable = None,
        on_disconnected: Callable = None,
        on_reconnected: Callable = None,
    ):
        """Set event callbacks."""
        self._on_agent_registered = on_registered
        self._on_agent_disconnected = on_disconnected
        self._on_agent_reconnected = on_reconnected

    @property
    def architect(self) -> Optional[str]:
        return self._architect

    def register_agent(
        self,
        model: str,
        version: str = None,
        capabilities: Dict = None,
        websocket_id: int = None,
        resource_request: Dict = None,
        session_id: str = None,
    ) -> tuple[AgentInfo, bool, str]:
        """Register a new agent or reconnect existing.

        Returns (agent_info, is_reconnect, session_id).
        """
        # Check for existing agent (reconnect)
        existing = None
        is_reconnect = False
        if self.storage:
            existing = self.storage.get_agent(model)

        if existing and session_id and existing.get("session_id") == session_id:
            is_reconnect = True

        # Determine role
        if is_reconnect and existing:
            role = existing.get("role", "agent")
        else:
            role = "architect" if self._architect is None else "agent"
            if role == "architect":
                self._architect = model

        # Create agent info
        if websocket_id is None:
            self._websocket_counter += 1
            websocket_id = self._websocket_counter

        agent = AgentInfo(
            model=model,
            version=version,
            capabilities=capabilities or {},
            role=role,
            websocket_id=websocket_id,
            resource_request=resource_request or {},
            session_id=session_id,
        )

        if is_reconnect:
            # Handle reconnect
            self._disconnect_deadline.pop(model, None)

            # Allocate hardware if not already allocated
            if self.hardware and model not in self.hardware.allocations:
                self.hardware.allocate(model, agent.resource_request)

            # Restore status from existing data
            current_task = existing.get("current_task") if existing else None
            agent.current_task = current_task

            prev_status = existing.get("status", "idle") if existing else "idle"
            if str(prev_status).lower() in {"disconnected", "offline"}:
                agent.status = "idle"
            else:
                agent.status = prev_status

            if self._on_agent_reconnected:
                self._on_agent_reconnected(model)
        else:
            # New agent - allocate hardware
            if self.hardware:
                if not self.hardware.allocate(model, agent.resource_request):
                    agent.status = "suspended"
                else:
                    agent.status = "idle"

            if not session_id:
                session_id = str(uuid.uuid4())
                agent.session_id = session_id

        self.agents[model] = agent

        # Persist to storage
        if self.storage:
            self.storage.upsert_agent(
                model,
                {
                    "session_id": session_id,
                    "role": role,
                    "status": agent.status,
                    "is_active": 1,
                    "connected_at": agent.connected_at,
                    "hardware_usage": agent.resource_request,
                },
            )

        if self._on_agent_registered:
            self._on_agent_registered(model)

        return agent, is_reconnect, session_id

    def get_agent(self, model: str) -> Optional[AgentInfo]:
        """Get agent by model name."""
        return self.agents.get(model)

    def get_agent_by_websocket_id(self, websocket_id: int) -> Optional[AgentInfo]:
        """Get agent by websocket ID."""
        for agent in self.agents.values():
            if agent.websocket_id == websocket_id:
                return agent
        return None

    def remove_agent(self, model: str) -> bool:
        """Remove an agent immediately.

        Returns True if agent existed and was removed.
        """
        if model not in self.agents:
            return False

        del self.agents[model]
        if self._architect == model:
            self._architect = None

        # Release hardware
        if self.hardware:
            self.hardware.release(model)

        # Update storage
        if self.storage:
            self.storage.upsert_agent(model, {"is_active": 0, "status": "offline"})

        return True

    def mark_disconnected(self, model: str) -> bool:
        """Mark agent as disconnected with grace period.

        Returns True if agent was marked for disconnect grace.
        """
        if model not in self.agents:
            return False

        # Already in grace period
        if model in self._disconnect_deadline:
            return False

        deadline = time.time() + self._disconnect_grace_sec
        self._disconnect_deadline[model] = deadline

        # Mark as disconnected
        self.agents[model].status = "disconnected"

        # Update storage
        if self.storage:
            self.storage.upsert_agent(model, {"is_active": 0, "status": "disconnected"})

        if self._on_agent_disconnected:
            self._on_agent_disconnected(model)

        return True

    def cancel_disconnect_grace(self, model: str) -> bool:
        """Cancel pending disconnect for a reconnected agent.

        Returns True if there was a pending disconnect.
        """
        if model in self._disconnect_deadline:
            del self._disconnect_deadline[model]
            return True
        return False

    def is_in_grace_period(self, model: str) -> bool:
        """Check if agent is in disconnect grace period."""
        return model in self._disconnect_deadline

    def get_expired_grace_periods(self) -> List[str]:
        """Get agents whose grace periods have expired."""
        now = time.time()
        expired = []
        for model, deadline in self._disconnect_deadline.items():
            if now >= deadline:
                expired.append(model)
        return expired

    def update_heartbeat(self, model: str) -> bool:
        """Update last_seen timestamp for an agent.

        Returns True if agent exists and was updated.
        """
        if model not in self.agents:
            return False

        self.agents[model].last_seen = datetime.now().isoformat()
        return True

    def update_status(self, model: str, status: str, current_task: str = None) -> bool:
        """Update agent status.

        Returns True if agent exists and was updated.
        """
        if model not in self.agents:
            return False

        self.agents[model].status = status
        if current_task is not None:
            self.agents[model].current_task = current_task

        # Update storage
        if self.storage:
            self.storage.upsert_agent(model, {"status": status})

        return True

    def get_active_agents(self) -> List[AgentInfo]:
        """Get all active (non-disconnected) agents."""
        return [a for a in self.agents.values() if a.status != "disconnected"]

    def get_all_agents(self) -> List[AgentInfo]:
        """Get all agents including disconnected."""
        return list(self.agents.values())

    def get_agent_summary(self) -> List[Dict]:
        """Get summary info for all agents."""
        return [
            {
                "model": a.model,
                "role": a.role,
                "status": a.status,
                "current_task": a.current_task,
            }
            for a in self.agents.values()
        ]

    def get_roster(self) -> Dict:
        """Get agent roster for coordination."""
        return {
            "architect": self._architect,
            "agents": self.get_agent_summary(),
        }

    def is_agent_active(self, model: str) -> bool:
        """Check if agent is currently active (not disconnected or suspended)."""
        agent = self.agents.get(model)
        if not agent:
            return False
        return agent.status not in {"disconnected", "suspended", "offline"}

    def get_available_agents(self) -> List[AgentInfo]:
        """Get agents available for task assignment."""
        return [a for a in self.agents.values() if a.status == "idle"]

    def set_agent_task(self, model: str, task_id: str = None) -> bool:
        """Set or clear the current task for an agent.

        Returns True if agent exists.
        """
        if model not in self.agents:
            return False

        self.agents[model].current_task = task_id
        if task_id:
            self.agents[model].status = "working"
        else:
            self.agents[model].status = "idle"

        return True
