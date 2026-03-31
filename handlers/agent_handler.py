"""
Agent WebSocket Handler
-------------------------
Handles WebSocket connections from AI agent clients.
"""

import asyncio
from typing import Dict, Optional, Callable, Any, Set
import websockets
import orjson

from security import validate_model_name, ValidationError
from rate_limit import get_rate_limiter, RateLimitExceeded


class AgentWebSocketHandler:
    """Handles agent WebSocket connections and messages."""

    def __init__(self, server):
        self.server = server
        self.clients: Set = set()

    async def handle(self, ws):
        """Main handler for agent WebSocket connections."""
        # Rate limit connection attempts by IP
        try:
            rate_limiter = get_rate_limiter()
            client_ip = ws.remote_address[0] if ws.remote_address else "unknown"
            await rate_limiter.check("agent_register", client_ip)
        except RateLimitExceeded as e:
            self.server.log.warning(f"Rate limit exceeded for agent connection from {client_ip}")
            await ws.close(code=1008, reason="Rate limit exceeded")
            return

        self.clients.add(ws)
        try:
            async for msg in ws:
                await self._handle_message(ws, msg)
        except websockets.exceptions.ConnectionClosed:
            # Expected during disconnects/reconnects
            pass
        except Exception as e:
            self.server.log.error(
                f"Error in agent handler for {getattr(ws, '_agent_id', 'unknown')}: {e}"
            )
        finally:
            await self._cleanup_connection(ws)

    async def _handle_message(self, ws, message: str):
        """Dispatch agent messages to appropriate handlers."""
        try:
            data = orjson.loads(message)
        except (ValueError, TypeError):
            await ws.send(orjson.dumps({"event": "error", "reason": "invalid_json"}))
            return

        ev = data.get("event", "")
        handler = self._get_handler(ev)

        if handler:
            result = await handler(ws, data)
            if result:
                await ws.send(orjson.dumps(result))
        else:
            await ws.send(
                orjson.dumps({"event": "error", "reason": f"unknown_event:{ev}"})
            )

    def _get_handler(self, event: str) -> Optional[Callable]:
        """Get the appropriate handler for an event type."""
        handlers = {
            "register": self._handle_register,
            "lock_request": self._handle_lock_request,
            "lock_release": self._handle_lock_release,
            "file_change": self._handle_file_change,
            "create_task": self._handle_task_event,
            "claim_task": self._handle_task_event,
            "start_task": self._handle_task_event,
            "complete_task": self._handle_task_event,
            "abandon_task": self._handle_task_event,
            "bid_task": self._handle_bid,
            "heartbeat": self._handle_heartbeat,
            "subscribe_file": self._handle_subscribe_file,
            "framework_ready": self._handle_framework_ready,
            "framework_patch": self._handle_framework_patch,
            "share_context": self._handle_share_context,
            "query_context": self._handle_query_context,
            "get_status": self._handle_get_status,
        }
        return handlers.get(event)

    async def _handle_register(self, ws, data: Dict) -> Dict:
        """Handle agent registration with validation."""
        model = data.get("model", "unknown")

        # Validate model name format
        try:
            validate_model_name(model)
        except ValidationError as e:
            self.server.log.warning(f"Invalid model name attempted: {model} - {e}")
            return {"event": "error", "reason": "invalid_model_name", "message": str(e)}

        # Rate limit registration by model name
        try:
            rate_limiter = get_rate_limiter()
            await rate_limiter.check("agent_register", model)
        except RateLimitExceeded as e:
            self.server.log.warning(f"Rate limit exceeded for model {model}")
            return {"event": "error", "reason": "rate_limited", "retry_after": e.retry_after}

        return await self.server._register(ws, data)

    async def _handle_lock_request(self, ws, data: Dict) -> Dict:
        """Handle lock request from agent with rate limiting."""
        model = data.get("model", "unknown")

        try:
            rate_limiter = get_rate_limiter()
            await rate_limiter.check("lock_request", model)
        except RateLimitExceeded as e:
            return {"event": "lock_denied", "reason": "rate_limited", "retry_after": e.retry_after}

        return await self.server._lock_request(data)

    async def _handle_lock_release(self, ws, data: Dict) -> Dict:
        """Handle lock release from agent."""
        return await self.server._lock_release(data)

    async def _handle_file_change(self, ws, data: Dict) -> Dict:
        """Handle file change notification from agent."""
        return await self.server._file_change(data)

    async def _handle_task_event(self, ws, data: Dict) -> Dict:
        """Handle task lifecycle events."""
        # Convert event name
        ev = data.get("event", "")
        data["event"] = ev.replace("_task", "")
        return await self.server._task_event(data)

    async def _handle_bid(self, ws, data: Dict) -> Dict:
        """Handle task bid from agent."""
        return await self.server._bid(data)

    async def _handle_heartbeat(self, ws, data: Dict) -> Dict:
        """Handle agent heartbeat."""
        model = data.get("model")
        ts_iso = self.server._ts()

        if model in self.server.agents:
            self.server.agents[model].last_seen = ts_iso
            self.server.storage.upsert_agent(model, {
                "status": self.server.agents[model].status,
                "last_seen": ts_iso
            })

        # Update lock heartbeat
        tgt = data.get("target")
        if tgt and tgt in self.server.locks:
            for lock in self.server.locks[tgt]:
                if lock.holder == model:
                    lock.last_heartbeat = ts_iso

        return {"event": "heartbeat_ack"}

    async def _handle_subscribe_file(self, ws, data: Dict) -> Dict:
        """Handle file subscription request."""
        fp = data.get("path")
        model = data.get("model")
        if fp and model:
            self.server.file_subs.setdefault(fp, set()).add(model)
        return {"event": "subscribe_ack", "path": fp}

    async def _handle_framework_ready(self, ws, data: Dict) -> Dict:
        """Handle framework ready notification."""
        model = data.get("model")
        overview = data.get("overview", "")
        project_dir = data.get("working_dir") or data.get("project_dir") or self.server.framework.get("project_dir")
        task_text = data.get("task_text") or self.server.framework.get("task_text")

        # Record framework and broadcast
        self.server.framework = {
            "status": "ready",
            "by": model,
            "task_text": task_text,
            "project_dir": project_dir,
            "overview": overview,
            "timestamp": self.server._ts(),
        }

        self.server._audit({"event": "framework_ready", "model": model, "working_dir": project_dir})
        await self.server._broadcast_agents({
            "event": "framework_ready",
            "model": model,
            "working_dir": project_dir,
            "overview": overview,
            "task_text": task_text,
        })

        # Broadcast task instruction
        if task_text and project_dir:
            await self.server._broadcast_agents({
                "event": "task_instruction",
                "text": task_text,
                "working_dir": project_dir,
                "framework_overview": overview,
                "from": "framework_gate",
                "timestamp": self.server._ts(),
            })
            self.server._audit({"event": "dashboard_task", "text": task_text, "working_dir": project_dir})

        asyncio.create_task(self.server._push_dash(self.server._full_state()))
        return {"event": "framework_ack"}

    async def _handle_framework_patch(self, ws, data: Dict) -> Dict:
        """Handle framework patch from agent."""
        model = data.get("model")
        patch_text = data.get("patch", "")
        new_overview = data.get("overview", "")

        if self.server.framework.get("status") != "ready":
            return {"event": "framework_patch_denied", "reason": "not_ready"}

        if new_overview:
            self.server.framework["overview"] = new_overview
        if patch_text:
            self.server.framework.setdefault("patches", []).append({
                "by": model,
                "patch": patch_text,
                "timestamp": self.server._ts(),
            })
        self.server.framework["last_edited_by"] = model
        self.server.framework["last_edited_at"] = self.server._ts()

        self.server._audit({"event": "framework_patched", "model": model, "working_dir": self.server.framework.get("project_dir")})
        await self.server._broadcast_agents({
            "event": "framework_patched",
            "model": model,
            "working_dir": self.server.framework.get("project_dir"),
            "overview": self.server.framework.get("overview", ""),
            "patch": patch_text,
        })
        asyncio.create_task(self.server._push_dash(self.server._full_state()))
        return {"event": "framework_patch_ack"}

    async def _handle_share_context(self, ws, data: Dict) -> Dict:
        """Handle context sharing from agent."""
        model, key, value = data.get("model"), data.get("key"), data.get("value")
        if key and value:
            self.server.storage.add_context_item(key, value, model, data.get("confidence", 1.0))
            self.server._audit({"event": "context_shared", "model": model, "key": key})
            return {"event": "share_context_ack", "ok": True}
        return {"event": "error", "reason": "missing_key_or_value"}

    async def _handle_query_context(self, ws, data: Dict) -> Dict:
        """Handle context query from agent."""
        query = data.get("query", "")
        query_id = data.get("query_id")
        results = self.server.storage.search_context(query)
        return {"event": "context_results", "query_id": query_id, "query": query, "results": results}

    async def _handle_get_status(self, ws, data: Dict) -> Dict:
        """Handle status request from agent."""
        return {
            "event": "status",
            "agents": {k: {"role": v.role, "status": v.status} for k, v in self.server.agents.items()},
            "tasks": {k: self.server._serialize_task(v) for k, v in self.server.tasks.items()},
            "hardware": self.server.hw.status()
        }

    async def _cleanup_connection(self, ws):
        """Clean up after agent disconnects."""
        self.clients.discard(ws)
        aid = getattr(ws, "_agent_id", None)
        for model, ag in list(self.server.agents.items()):
            if ag.websocket_id == aid:
                self.server._drop_agent(model, reason="disconnect")
                break

    async def broadcast(self, payload: Dict):
        """Broadcast message to all agent clients."""
        if not self.clients:
            return
        msg = orjson.dumps(payload)
        await asyncio.gather(
            *[c.send(msg) for c in self.clients],
            return_exceptions=True
        )

    async def send_to_agent(self, model: str, payload: Dict) -> bool:
        """Send message to specific agent."""
        if model not in self.server.agents:
            return False

        target_id = self.server.agents[model].websocket_id
        msg = orjson.dumps(payload)

        for ws in list(self.clients):
            if getattr(ws, "_agent_id", None) == target_id:
                try:
                    await ws.send(msg)
                    return True
                except Exception:
                    pass
        return False
