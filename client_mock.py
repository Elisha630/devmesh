import argparse
import asyncio
import json
import random
import sys
from typing import Dict, Optional

import websockets

HOST = "127.0.0.1"
PORT = 7700


class MockClient:
    def __init__(self, model: str, resources: Dict):
        self.model = model
        self.resources = resources
        self.ws = None
        self.role = None
        self.events = {
            "registered": asyncio.Event(),
            "framework_ready": asyncio.Event(),
            "lock_granted": asyncio.Event(),
            "task_claimed": asyncio.Event(),
        }
        self.state = {
            "tasks": {},
            "locks": set(),
            "current_task": None,
        }
        self.pending_requests = {}  # id -> future

    async def connect(self):
        uri = f"ws://{HOST}:{PORT}"
        print(f"[{self.model}] Connecting to {uri}...")
        self.ws = await websockets.connect(uri)
        
        # Start listener
        asyncio.create_task(self.listen())
        
        # Register
        await self.send({
            "event": "register",
            "model": self.model,
            "version": "2.0",
            "capabilities": {"languages": ["python", "javascript", "sql"]},
            "resources": self.resources,
        })
        
        await self.events["registered"].wait()
        print(f"[{self.model}] ✓ Registered as {self.role}")

    async def listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                await self.handle_message(data)
        except websockets.exceptions.ConnectionClosed:
            print(f"[{self.model}] Connection closed")
        except Exception as e:
            print(f"[{self.model}] Error in listener: {e}")

    async def handle_message(self, data: Dict):
        event = data.get("event")
        
        # Handle responses / acks
        if event == "registered":
            self.role = data.get("role")
            self.events["registered"].set()
        
        elif event == "framework_ready":
            print(f"[{self.model}] 🔔 Framework is READY")
            self.events["framework_ready"].set()

        elif event == "lock_granted":
            target = data.get("target")
            if data.get("model") == self.model:
                self.state["locks"].add(target)
                self.events["lock_granted"].set()
                print(f"[{self.model}] 🔓 Lock acquired: {target}")

        elif event == "task_created":
            task = data.get("task")
            self.state["tasks"][task["task_id"]] = task
            # print(f"[{self.model}] New task: {task['task_id']}")

        elif event == "task_completed":
            task_id = data.get("task_id")
            if task_id in self.state["tasks"]:
                self.state["tasks"][task_id]["status"] = "completed"
            print(f"[{self.model}] Task {task_id} completed")

        elif event == "status":
            self.state["tasks"] = data.get("tasks", {})

        elif event == "claim_ack":
            # We claimed a task
            pass 

    async def send(self, payload: Dict):
        await self.ws.send(json.dumps(payload))

    async def run_architect(self):
        print(f"[{self.model}] 🏗️  Starting ARCHITECT workflow")
        
        # Create tasks
        tasks_def = [
            {"task_id": "T001", "desc": "Project Skeleton", "file": "framework.json", "deps": []},
            {"task_id": "T002", "desc": "Main Module", "file": "src/main.py", "deps": ["T001"]},
            {"task_id": "T003", "desc": "Utils Module", "file": "src/utils.py", "deps": ["T001"]},
        ]
        
        for t in tasks_def:
            await self.send({
                "event": "create_task", "model": self.model,
                "task_id": t["task_id"], "description": t["desc"], 
                "file": t["file"], "depends_on": t["deps"],
                "operation": "create", "priority": 1
            })
            await asyncio.sleep(0.1)

        # Do T001
        print(f"[{self.model}] Claiming T001...")
        await self.send({"event": "claim_task", "task_id": "T001", "model": self.model})
        await self.send({"event": "start_task", "task_id": "T001", "model": self.model})
        
        # Lock
        self.events["lock_granted"].clear()
        await self.send({"event": "lock_request", "model": self.model, "target": "framework.json", "type": "write"})
        await self.events["lock_granted"].wait()
        
        # Work
        await asyncio.sleep(2) # Simulate thinking
        await self.send({"event": "file_change", "model": self.model, "path": "framework.json", "content": "{}"})
        
        # Release
        await self.send({"event": "lock_release", "model": self.model, "target": "framework.json"})
        await self.send({"event": "complete_task", "task_id": "T001", "model": self.model})
        
        # Signal Ready
        await self.send({"event": "framework_ready", "model": self.model})
        print(f"[{self.model}] ✅ Framework built. T001 Done.")

    async def run_agent(self):
        print(f"[{self.model}] 👷 Starting AGENT workflow. Waiting for framework...")
        
        # Check if we missed the event
        await self.send({"event": "get_status", "model": self.model})
        await asyncio.sleep(0.5)
        
        t001 = self.state["tasks"].get("T001")
        if t001 and t001.get("status") == "completed":
            print(f"[{self.model}] 💡 Framework already ready (detected via T001)")
            self.events["framework_ready"].set()
        
        await self.events["framework_ready"].wait()
        
        # Poll for tasks
        while True:
            # Refresh status
            await self.send({"event": "get_status", "model": self.model})
            await asyncio.sleep(0.5)
            
            # Find task
            my_task = None
            for tid, t in self.state["tasks"].items():
                # Check if dependencies are met
                deps_met = all(
                    self.state["tasks"].get(d, {}).get("status") == "completed" 
                    for d in t["depends_on"]
                )
                if t["status"] == "queued" and deps_met:
                    my_task = t
                    break
            
            if my_task:
                tid = my_task["task_id"]
                print(f"[{self.model}] 🙋 Found task {tid}. Claiming...")
                await self.send({"event": "claim_task", "task_id": tid, "model": self.model})
                
                # Assume claim success for demo speed (race conditions possible but ok for mock)
                await self.send({"event": "start_task", "task_id": tid, "model": self.model})
                
                # Lock
                target = my_task["file"]
                self.events["lock_granted"].clear()
                await self.send({"event": "lock_request", "model": self.model, "target": target, "type": "write"})
                
                # Wait for lock (with timeout)
                try:
                    await asyncio.wait_for(self.events["lock_granted"].wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    print(f"[{self.model}] ❌ Lock timeout on {target}")
                    continue

                # Work
                print(f"[{self.model}] 🔨 Working on {target}...")
                await asyncio.sleep(random.uniform(1.5, 3.0))
                await self.send({"event": "file_change", "model": self.model, "path": target, "content": "..."})
                
                # Done
                await self.send({"event": "lock_release", "model": self.model, "target": target})
                await self.send({"event": "complete_task", "task_id": tid, "model": self.model})
                print(f"[{self.model}] ✅ Task {tid} Done.")
                break # Do one task then chill for demo
            else:
                await asyncio.sleep(1)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="mock-model")
    parser.add_argument("--vram", type=float, default=2)
    parser.add_argument("--ram", type=float, default=4)
    args = parser.parse_args()
    
    client = MockClient(args.model, {"vram_gb": args.vram, "ram_gb": args.ram})
    await client.connect()
    
    if client.role == "architect":
        await client.run_architect()
    else:
        await client.run_agent()
        
    await asyncio.sleep(5) # Keep connection alive for a bit

if __name__ == "__main__":
    asyncio.run(main())
