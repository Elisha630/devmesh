"""
agent_bridge.py — DevMesh Agent Bridge (v3.1)
--------------------------------------------
Wraps a local AI CLI tool so it can connect to the DevMesh coordinator.
Includes Phase 2 Resilience: Session persistence and automatic reconnection.
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import websockets

from config import get_agent_config, get_server_config, TOOL_PROFILES
from logger import setup_logging, get_logger
from errors import ToolNotFound, ToolInvokeError


class AgentBridge:
    def __init__(self, tool_name: str, ws_url: str):
        self.tool_name  = tool_name
        self.ws_url     = ws_url
        self.profile    = TOOL_PROFILES.get(tool_name)
        if not self.profile:
            raise ToolNotFound(tool_name)
        self.model_id   = tool_name
        self.ws         = None
        self.role       = None
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self._task_counter = 0
        self._lock_wait = asyncio.Event()
        self._pending_lock_target = None
        self._pending_lock_denied_reason = None
        self._current_lock_target = None
        self.rulebook = None
        self.memory = None
        self.roster = None
        self.framework_ready = asyncio.Event()
        self.log = get_logger("bridge")

        # Shared-context query coordination (only one query at a time per bridge).
        self._pending_context_query_id = None
        self._context_results_event = asyncio.Event()
        self._context_results = []
        
        # Phase 2: Session recovery
        self.session_id = self._load_session()
        self.log.debug(f"Initialized bridge for {tool_name} (Session: {self.session_id or 'New'})")

    def _session_path(self) -> Path:
        """✅ FIX 2.3: Write session files to a fixed location, not cwd."""
        base = get_server_config().audit_log_dir
        base.mkdir(parents=True, exist_ok=True)
        return base / f".devmesh_session_{self.tool_name}"

    def _load_session(self) -> Optional[str]:
        session_file = self._session_path()
        if session_file.exists():
            try:
                return session_file.read_text().strip()
            except Exception:
                pass
        return None

    def _save_session(self, session_id: str):
        self.session_id = session_id
        try:
            self._session_path().write_text(session_id)
        except Exception as e:
            self.log.warning(f"Failed to save session_id: {e}")

    async def _send(self, payload: dict):
        if self.ws:
            try:
                await self.ws.send(json.dumps(payload))
            except Exception as e:
                self.log.error(f"Failed to send message: {e}")

    async def _recv_loop(self):
        """Listen for messages from DevMesh server."""
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                ev = msg.get("event", "")

                if ev == "registered":
                    self.role = msg.get("role", "agent")
                    self.rulebook = msg.get("rulebook")
                    self.memory = msg.get("memory")
                    self.roster = msg.get("roster")
                    new_session = msg.get("session_id")
                    if new_session:
                        self._save_session(new_session)
                    self.log.info(f"Registered as {self.role} (Session: {self.session_id})")

                elif ev == "agent_roster":
                    self.roster = msg.get("roster")

                elif ev == "task_instruction":
                    text = msg.get("text", "")
                    working_dir = msg.get("working_dir", "/tmp")
                    target_file = msg.get("target_file")
                    self.log.info(f"Task received: {text[:80]}")
                    await self.task_queue.put({
                        "text": text,
                        "working_dir": working_dir,
                        "target_file": target_file,
                        "ts": msg.get("timestamp", "")
                    })

                elif ev == "task_created":
                    task = msg.get("task", {})
                    self.log.info(f"Task created: {task.get('task_id')} — {task.get('description', '')[:60]}")

                elif ev == "lock_granted":
                    if msg.get("model") == self.model_id and msg.get("target") == self._pending_lock_target:
                        self._pending_lock_denied_reason = None
                        self._current_lock_target = self._pending_lock_target
                        self._lock_wait.set()

                elif ev == "lock_denied":
                    if msg.get("target") == self._pending_lock_target:
                        self._pending_lock_denied_reason = msg.get("reason", "lock_denied")
                        self._lock_wait.set()

                elif ev == "framework_ready":
                    self.framework_ready.set()
                    self.log.info("Framework ready — execution may begin")

                elif ev == "context_results":
                    qid = msg.get("query_id")
                    if self._pending_context_query_id and qid == self._pending_context_query_id:
                        self._context_results = msg.get("results", [])
                        self._context_results_event.set()
                        self.log.debug(f"Context query {qid} returned {len(self._context_results)} items")

                elif ev == "framework_pending":
                    self.framework_ready.clear()

                elif ev == "framework_request":
                    if self.role != "architect":
                        continue
                    task_text = msg.get("task_text", "")
                    working_dir = msg.get("working_dir", "/tmp")
                    prompt = (
                        "You are the ARCHITECT. Produce a concise overview/skeleton for the task.\n"
                        "Must include:\n"
                        "- The exact working_dir (project folder) to use\n"
                        "- A proposed folder/file skeleton (tree)\n"
                        "- Task breakdown (3-8 bullets) for other agents to take distinct deliverables\n"
                        "Rules:\n"
                        "- Choose sensible defaults; do not ask questions unless blocked.\n"
                        "- Keep it short but concrete.\n\n"
                        f"Task: {task_text}\n"
                        f"working_dir: {working_dir}\n"
                    )
                    overview = await self._invoke_tool(prompt, working_dir=working_dir)
                    await self._send({
                        "event": "framework_ready",
                        "model": self.model_id,
                        "task_text": task_text,
                        "working_dir": working_dir,
                        "overview": overview,
                    })

        except Exception as e:
            self.log.error(f"Recv loop ended: {e}")

    async def _work_loop(self):
        """Process tasks from the queue by calling the real CLI."""
        while True:
            task = await self.task_queue.get()
            text = task["text"]
            working_dir = task.get("working_dir", "/tmp")
            target_file = task.get("target_file")
            
            if not self.framework_ready.is_set():
                try:
                    await asyncio.wait_for(self.framework_ready.wait(), timeout=600.0)
                except asyncio.TimeoutError:
                    self.log.error("Framework not ready after 600s; abandoning queued task.")
                    continue
            
            wd_path = Path(working_dir).expanduser()
            if not wd_path.exists() or not wd_path.is_dir():
                self.log.warning(f"Working dir invalid: {working_dir}. Using /tmp.")
                wd_path = Path("/tmp")

            # If server asks us to resolve/overwrite a specific artifact,
            # use that exact path instead of generating a new output file.
            if target_file:
                out_path = Path(target_file).expanduser()
                try:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    wd_path = out_path.parent
                    working_dir = str(wd_path)
                except Exception:
                    # Fallback to working_dir if target_file is unusable.
                    target_file = None

            self._task_counter += 1
            task_id   = f"T{self._task_counter:03d}-{self.tool_name}"
            if not target_file:
                out_file  = f"devmesh_output_{self.tool_name}_{self._task_counter}.md"
                out_path  = wd_path / out_file

            # Register task with server
            await self._send({
                "event": "create_task",
                "model": self.model_id,
                "task_id": task_id,
                "description": text[:120],
                "file": str(out_path),
                "operation": "create",
                "working_dir": str(wd_path),
            })
            await asyncio.sleep(0.1)
            await self._send({"event": "claim_task",  "task_id": task_id, "model": self.model_id})
            await self._send({"event": "start_task",  "task_id": task_id, "model": self.model_id})

            # Acquire write lock
            self._pending_lock_target = str(out_path)
            self._pending_lock_denied_reason = None
            self._lock_wait.clear()
            await self._send({"event": "lock_request", "model": self.model_id,
                               "target": str(out_path), "type": "write"})
            try:
                await asyncio.wait_for(self._lock_wait.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                self.log.error(f"Lock timeout on {out_path}; abandoning task {task_id}")
                await self._send({"event": "abandon_task", "task_id": task_id, "model": self.model_id})
                continue

            if self._pending_lock_denied_reason:
                self.log.error(f"Lock denied on {out_path}: {self._pending_lock_denied_reason}")
                await self._send({"event": "abandon_task", "task_id": task_id, "model": self.model_id})
                continue

            self.log.info(f"Running {self.profile['label']} on task…")

            try:
                context_items = await self._query_shared_context(text, timeout_sec=8.0)
                output, raw_stdout, raw_stderr = await self._invoke_tool(
                    text,
                    str(wd_path),
                    context_items=context_items,
                    return_raw=True,
                )
            except ToolInvokeError as e:
                self.log.error(f"Tool invocation failed: {e.message}")
                output = f"**Error:** {e.message}"
                raw_stdout, raw_stderr = "", e.message

            # Write output file
            out_path.write_text(
                f"# DevMesh Task\n\n**Prompt:** {text}\n\n**Model:** {self.profile['label']}\n\n---\n\n{output}\n",
                encoding="utf-8",
            )

            # Report file change
            await self._send({
                "event":     "file_change",
                "model":     self.model_id,
                "path":      str(out_path),
                "operation": "create",
                "content":   output[:500],
                "stdout":    raw_stdout[:20000],
                "stderr":    raw_stderr[:20000],
                "diff":      f"+++ {out_path}\n{output[:200]}",
            })

            # Release lock and complete task
            await self._send({"event": "lock_release", "model": self.model_id, "target": str(out_path)})
            if self._current_lock_target == str(out_path):
                self._current_lock_target = None
            await self._send({"event": "complete_task", "task_id": task_id, "model": self.model_id})
            self.log.info(f"Task {task_id} complete → {out_path}")

    async def _query_shared_context(self, query_text: str, timeout_sec: float = 6.0):
        """Ask the server for relevant shared discoveries (RAG) for this query."""
        fallback = (self.memory or {}).get("context") or []
        if not query_text or not str(query_text).strip():
            return fallback
        if not self.ws:
            return fallback

        qid = str(uuid.uuid4())
        self._pending_context_query_id = qid
        self._context_results_event.clear()
        try:
            await self._send({
                "event": "query_context",
                "model": self.model_id,
                "query": query_text,
                "query_id": qid,
            })
            await asyncio.wait_for(self._context_results_event.wait(), timeout=timeout_sec)
            return self._context_results or fallback
        except asyncio.TimeoutError:
            return fallback
        finally:
            self._pending_context_query_id = None

    async def _invoke_tool(self, prompt: str, working_dir: str = "/tmp", context_items=None, return_raw: bool = False):
        """Call the real CLI tool and return its output.

        If `return_raw` is True, return `(output, raw_stdout, raw_stderr)`.
        """
        mode = self.profile.get("invoke_mode", "arg")
        cfg = get_agent_config(tool_name=self.tool_name, ws_url=self.ws_url)

        if mode == "note":
            out = (
                f"*{self.profile['label']} is a GUI editor and cannot be driven via command line.*\n\n"
                f"Open {self.tool_name} and paste this prompt manually:\n\n> {prompt}"
            )
            return (out, "", "") if return_raw else out

        cmd_template = self.profile.get("cmd", [])
        if not cmd_template:
            raise ToolInvokeError(self.tool_name, "no command configured")

        wd_path = Path(working_dir).expanduser()
        wd_str = str(wd_path)

        def _subst(s: str) -> str:
            return (
                s.replace("{prompt}", prompt)
                 .replace("{working_dir}", wd_str)
            )

        mem_obj = self.memory or {}
        context_src = context_items if context_items is not None else (mem_obj.get("context") or [])
        # Compact context so it fits inside CLI prompt size.
        compact_context = []
        for it in (context_src or [])[:10]:
            if not isinstance(it, dict):
                continue
            k = (it.get("key") or "").strip()
            v = it.get("value") or ""
            v = v[:1000] if isinstance(v, str) else ""
            if not k or not v:
                continue
            compact_context.append({
                "key": k,
                "value": v,
                "source_agent": it.get("source_agent"),
                "confidence_score": it.get("confidence_score"),
                "timestamp": it.get("timestamp"),
            })

        mem_compact = {
            "recent_tasks": (mem_obj.get("recent_tasks") or [])[-10:],
            "agents": (mem_obj.get("agents") or []),
            "context_items": compact_context,
        }
        mem = json.dumps(mem_compact, separators=(",", ":"), ensure_ascii=False)
        roster = json.dumps(self.roster or {}, separators=(",", ":"), ensure_ascii=False)
        
        prompt = (
            "<devmesh_context>\n"
            f"tool: {self.tool_name}\n"
            f"role: {self.role or 'agent'}\n"
            f"working_dir: {wd_str}\n"
            f"session_id: {self.session_id}\n"
            "\n"
            "operating_mode:\n"
            "- Do not ask clarifying questions unless absolutely blocked.\n"
            "- Choose sensible defaults and complete the task end-to-end.\n"
            "- Apply changes directly instead of providing copy-paste instructions.\n"
            "- Other agents are running in parallel. Avoid duplicate work.\n"
            "\n"
            "agent_roster_json:\n"
            f"{roster}\n"
            "\n"
            "context_json:\n"
            f"{mem}\n"
            "</devmesh_context>\n\n"
            f"{prompt}"
        )

        cmd = [_subst(c) for c in cmd_template]
        if self.tool_name == "gemini":
            gem_model = os.getenv("DEVMESH_GEMINI_MODEL", "").strip()
            if gem_model and "--model" not in cmd:
                cmd = [cmd[0], "--model", gem_model, *cmd[1:]]

        raw_stdout = ""
        raw_stderr = ""
        try:
            timeout_sec = cfg.cli_invoke_timeout_sec
            if mode == "stdin":
                proc = await asyncio.create_subprocess_exec(
                    *cmd, cwd=wd_str, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=prompt.encode()), timeout=timeout_sec
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, cwd=wd_str, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)

            raw_stdout = (stdout or b"").decode(errors="replace")
            raw_stderr = (stderr or b"").decode(errors="replace")

            output = raw_stdout.strip()
            err = raw_stderr.strip()
            if not output and err:
                output = f"(stderr) {err}"
            elif not output:
                output = "(no output)"

            return (output, raw_stdout, raw_stderr) if return_raw else output

        except asyncio.TimeoutError:
            try:
                if 'proc' in locals() and proc.returncode is None:
                    proc.kill()
                    stdout, stderr = await proc.communicate()
                    out = (stdout or b"").decode(errors="replace").strip()
                    err = (stderr or b"").decode(errors="replace").strip()
                    msg = out or (f"(stderr) {err}" if err else "(no output)")
                    raise ToolInvokeError(self.tool_name, f"timeout; partial output:\n{msg[:2000]}")
            except ToolInvokeError: raise
            except Exception: pass
            raise ToolInvokeError(self.tool_name, f"timeout (>{timeout_sec}s)")
        except FileNotFoundError:
            raise ToolInvokeError(self.tool_name, f"command not found: {cmd[0]}")
        except Exception as e:
            raise ToolInvokeError(self.tool_name, str(e))

    async def _heartbeat_loop(self):
        """Keep the connection alive."""
        cfg = get_agent_config(tool_name=self.tool_name, ws_url=self.ws_url)
        while True:
            await asyncio.sleep(cfg.heartbeat_interval_sec)
            payload = {"event": "heartbeat", "model": self.model_id}
            if self._current_lock_target:
                payload["target"] = self._current_lock_target
            await self._send(payload)

    async def run(self):
        """Main loop with reconnection logic."""
        cfg = get_agent_config(tool_name=self.tool_name, ws_url=self.ws_url)
        retry_delay = 1
        
        while True:
            self.log.info(f"Connecting to DevMesh at {self.ws_url}…")
            try:
                async with websockets.connect(self.ws_url, ping_interval=cfg.ping_interval_sec) as ws:
                    self.ws = ws
                    self.log.info("Connected ✓")
                    retry_delay = 1 # Reset on success

                    # Register (including session_id if we have one)
                    await self._send({
                        "event":        "register",
                        "model":        self.model_id,
                        "session_id":   self.session_id,
                        "version":      self.profile.get("label", self.tool_name),
                        "capabilities": self.profile.get("capabilities", {}),
                        "resources":    self.profile.get("resources", {}),
                    })

                    # ✅ FIX 3.5: Use wait() instead of gather() to handle WebSocket closure properly
                    recv_task = asyncio.create_task(self._recv_loop())
                    work_task = asyncio.create_task(self._work_loop())
                    beat_task = asyncio.create_task(self._heartbeat_loop())
                    
                    done, pending = await asyncio.wait(
                        [recv_task, work_task, beat_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # If any critical task completes, cancel the rest
                    for task in pending:
                        task.cancel()
                    
                    # Re-raise any exception from completed tasks
                    for task in done:
                        try:
                            task.result()
                        except asyncio.CancelledError:
                            pass
                        except Exception as e:
                            raise e
            except (ConnectionRefusedError, websockets.exceptions.ConnectionClosed):
                self.log.warning(f"Connection lost. Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)
            except Exception as e:
                self.log.error(f"Bridge error: {e}")
                await asyncio.sleep(5)


def main():
    parser = argparse.ArgumentParser(
        description="DevMesh Agent Bridge — connects an AI CLI to the DevMesh coordinator"
    )
    parser.add_argument("--tool", required=True,
                        choices=list(TOOL_PROFILES.keys()),
                        help="Which tool to bridge (e.g. claude, gemini, codex)")
    parser.add_argument("--ws",   default="ws://127.0.0.1:7700",
                        help="DevMesh agent WebSocket URL (default: ws://127.0.0.1:7700)")
    args = parser.parse_args()

    log = setup_logging(log_level="INFO")
    
    log.info(f"DevMesh Agent Bridge")
    log.info(f"  Tool:   {TOOL_PROFILES[args.tool]['label']}")
    log.info(f"  Server: {args.ws}")

    try:
        asyncio.run(AgentBridge(args.tool, args.ws).run())
    except KeyboardInterrupt:
        log.info("Shutdown requested")


if __name__ == "__main__":
    main()
