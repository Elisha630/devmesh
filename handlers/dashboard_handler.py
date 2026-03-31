"""
Dashboard WebSocket Handler
-----------------------------
Handles WebSocket connections from browser dashboard clients.
"""

import asyncio
from typing import Dict, Set
from pathlib import Path
import orjson
import websockets

from security import sanitize_path, validate_task_input, ValidationError, PathTraversalError
from rate_limit import get_rate_limiter, RateLimitExceeded


class DashboardWebSocketHandler:
    """Handles dashboard WebSocket connections and messages."""

    def __init__(self, server):
        self.server = server
        self.clients: Set = set()

    async def handle(self, ws, path=""):
        """Main handler for dashboard WebSocket connections."""
        # Rate limit dashboard connections
        try:
            rate_limiter = get_rate_limiter()
            client_ip = ws.remote_address[0] if ws.remote_address else "unknown"
            await rate_limiter.check("ws_message", client_ip)
        except RateLimitExceeded:
            self.server.log.warning(
                f"Rate limit exceeded for dashboard connection from {client_ip}"
            )
            await ws.close(code=1008, reason="Rate limit exceeded")
            return

        self.clients.add(ws)
        try:
            # Send initial state
            await ws.send(orjson.dumps(self.server._full_state()))

            async for msg in ws:
                try:
                    data = orjson.loads(msg)
                    await self._handle_message(data)
                except Exception as e:
                    self.server.log.error(f"Error processing dashboard message: {e}")
        except (websockets.exceptions.ConnectionClosed, ConnectionResetError):
            # Normal disconnect/reset
            pass
        finally:
            self.clients.discard(ws)

    async def _handle_message(self, data: Dict):
        """Dispatch dashboard messages to appropriate handlers."""
        msg_type = data.get("type")

        if msg_type == "chat":
            await self._handle_chat(data)
        elif msg_type == "get_state":
            await self.server._push_dash(self.server._full_state())
        elif msg_type == "create_task":
            await self._handle_create_task(data)
        elif msg_type == "rescan_tools":
            await self._handle_rescan_tools()
        elif msg_type == "launch_agent":
            await self._handle_launch_agent(data)
        elif msg_type == "stop_agent":
            await self._handle_stop_agent(data)
        else:
            self.server.log.warning(f"Unknown dashboard message type: {msg_type}")

    async def _handle_chat(self, data: Dict):
        """Handle chat message from dashboard with input validation."""
        text = data.get("text", "").strip()
        working_dir = data.get("working_dir", "/tmp").strip()

        if not text:
            return

        # Validate task input
        try:
            text = validate_task_input(text)
        except ValidationError as e:
            self.server.log.warning(f"Invalid task input: {e}")
            reply = {
                "sender": "system",
                "text": f"⚠ Invalid task: {e}",
                "timestamp": self.server._ts(),
            }
            self.server.chat_log.append(reply)
            await self.push({"type": "chat_message", "data": reply})
            return

        # Rate limit task submissions per IP/session
        try:
            rate_limiter = get_rate_limiter()
            await rate_limiter.check("task_submit", "dashboard")
        except RateLimitExceeded as e:
            self.server.log.warning(f"Task submission rate limit exceeded")
            reply = {
                "sender": "system",
                "text": f"⚠ Rate limit exceeded. Retry after {e.retry_after:.0f}s",
                "timestamp": self.server._ts(),
            }
            self.server.chat_log.append(reply)
            await self.push({"type": "chat_message", "data": reply})
            return

        # Validate working directory with path traversal protection
        try:
            wd_path = sanitize_path(working_dir)
            if not wd_path.exists():
                self.server.log.warning(f"Working dir does not exist: {working_dir}")
                reply = {
                    "sender": "system",
                    "text": f"⚠ Working directory not found: {working_dir}. Using /tmp instead.",
                    "timestamp": self.server._ts(),
                }
                self.server.chat_log.append(reply)
                await self.push({"type": "chat_message", "data": reply})
                working_dir = "/tmp"
        except (ValidationError, PathTraversalError) as e:
            self.server.log.warning(f"Invalid working dir: {working_dir} - {e}")
            reply = {
                "sender": "system",
                "text": f"⚠ Invalid working directory. Using /tmp instead.",
                "timestamp": self.server._ts(),
            }
            self.server.chat_log.append(reply)
            await self.push({"type": "chat_message", "data": reply})
            working_dir = "/tmp"

        project_dir = self.server._select_or_create_project_folder(working_dir, text)

        entry = {
            "sender": "user",
            "text": text,
            "working_dir": working_dir,
            "timestamp": self.server._ts(),
        }
        self.server.chat_log.append(entry)

        self.server.framework = {
            "status": "pending",
            "task_text": text,
            "project_dir": project_dir,
            "base_dir": working_dir,
            "timestamp": self.server._ts(),
        }
        self.server._audit({"event": "framework_pending", "working_dir": project_dir, "text": text})

        await self.server._broadcast_agents(
            {
                "event": "framework_pending",
                "working_dir": project_dir,
                "task_text": text,
                "from": "dashboard",
                "timestamp": entry["timestamp"],
            }
        )

        if self.server.architect:
            await self.server._send_to_agent(
                self.server.architect,
                {
                    "event": "framework_request",
                    "task_text": text,
                    "working_dir": project_dir,
                    "timestamp": entry["timestamp"],
                },
            )

        await self.push({"type": "chat_message", "data": entry})

        # Provide feedback
        if not self.server.agents:
            reply = {
                "sender": "system",
                "text": "⚠ No agents connected. Connect an agent first, then send the task.",
                "timestamp": self.server._ts(),
            }
        else:
            n = len(self.server.agents)
            reply = {
                "sender": "system",
                "text": f"Framework gate started for {n} agent{'s' if n != 1 else ''} in {project_dir}",
                "timestamp": self.server._ts(),
            }

            if not self.server.architect:
                await self.server._broadcast_agents(
                    {
                        "event": "task_instruction",
                        "text": text,
                        "working_dir": project_dir,
                        "from": "dashboard_direct",
                        "timestamp": entry["timestamp"],
                    }
                )

        self.server.chat_log.append(reply)
        await self.push({"type": "chat_message", "data": reply})

    async def _handle_create_task(self, data: Dict):
        """Handle task creation from dashboard."""
        data["event"] = "create"
        data["model"] = "dashboard"
        result = await self.server._task_event(data)
        await self.push({"type": "task_ack", "data": result})

    async def _handle_rescan_tools(self):
        """Handle tool rescan request."""
        from server import detect_installed_tools

        self.server.detected_tools = detect_installed_tools()
        await self.push(self.server._full_state())

    async def _handle_launch_agent(self, data: Dict):
        """Handle agent launch request."""
        tool_name = data.get("tool_name")
        result = await self.server._launch_agent(tool_name)
        await self.push({"type": "launch_result", "data": result})

    async def _handle_stop_agent(self, data: Dict):
        """Handle agent stop request."""
        tool_name = data.get("tool_name")
        result = self.server._stop_agent(tool_name)

        # Remove matching agents immediately
        for model in list(self.server.agents.keys()):
            if model == tool_name or model.startswith(tool_name):
                self.server._agent_disconnect_deadline.pop(model, None)
                self.server.hw.release(model)
                del self.server.agents[model]
                if self.server.architect == model:
                    self.server.architect = None
                self.server.storage.upsert_agent(model, {"is_active": 0, "status": "offline"})
                self.server._audit({"event": "agent_stopped", "model": model})

        await self.push({"type": "stop_result", "data": result})
        await self.push(self.server._full_state())

    async def push(self, payload: Dict):
        """Push message to all dashboard clients."""
        if not self.clients:
            return
        msg = orjson.dumps(payload)
        await asyncio.gather(*[c.send(msg) for c in self.clients], return_exceptions=True)

    async def push_throttled(self, payload: Dict):
        """Push to dashboard with throttling for full state updates."""
        if not self.clients:
            return

        import time

        # Check if this is a full state push
        is_full_state = all(k in payload for k in ["agents", "tasks", "locks"])

        if is_full_state:
            now = time.time()
            interval = getattr(self.server, "_full_state_push_interval", 0.5)
            last_push = getattr(self.server, "_last_full_state_push", 0.0)

            if now - last_push >= interval:
                self.server._last_full_state_push = now
                await self.push(payload)
            # else: throttle this full state push
        else:
            await self.push(payload)

    async def push_event(self, event: Dict):
        """Push event to dashboard and log it."""
        event.setdefault("timestamp", self.server._ts())
        self.server.event_log.append(event)
        if len(self.server.event_log) > 500:
            self.server.event_log = self.server.event_log[-500:]
        await self.push({"type": "event", "data": event})
