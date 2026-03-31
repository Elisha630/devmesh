"""
Task Manager Service
--------------------
Manages task lifecycle for the DevMesh multi-agent system.
"""

from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from models import TaskInfo, TaskState


class TaskManager:
    """Manages task queue, assignment, and lifecycle."""

    def __init__(self, storage=None):
        self.tasks: Dict[str, TaskInfo] = {}
        self.storage = storage
        self._on_task_created: Optional[Callable[[TaskInfo], Any]] = None
        self._on_task_claimed: Optional[Callable[[str, str], Any]] = None
        self._on_task_completed: Optional[Callable[[str], Any]] = None

    def set_callbacks(
        self,
        on_task_created: Callable = None,
        on_task_claimed: Callable = None,
        on_task_completed: Callable = None,
    ):
        """Set event callbacks."""
        self._on_task_created = on_task_created
        self._on_task_claimed = on_task_claimed
        self._on_task_completed = on_task_completed

    def create_task(
        self,
        task_id: str,
        description: str,
        file: str = "",
        operation: str = "create",
        priority: int = 1,
        depends_on: List[str] = None,
        required_capabilities: List[str] = None,
        critic_required: bool = False,
        created_by: str = "dashboard",
    ) -> Optional[TaskInfo]:
        """Create a new task.

        Returns the TaskInfo on success, None if task_id already exists.
        """
        if task_id in self.tasks:
            return None

        task = TaskInfo(
            task_id=task_id,
            description=description,
            file=file,
            operation=operation,
            priority=priority,
            depends_on=depends_on or [],
            required_capabilities=required_capabilities or [],
            critic_required=critic_required,
            created_by=created_by,
        )
        self.tasks[task_id] = task

        # Persist to storage
        if self.storage:
            self.storage.upsert_task(task_id, {
                "description": task.description,
                "status": task.status.value,
                "owner_model": task.owner_model,
                "working_dir": task.working_dir,
                "file_target": task.file,
                "created_at": task.created_at,
            })

        if self._on_task_created:
            self._on_task_created(task)

        return task

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """Get a task by ID."""
        return self.tasks.get(task_id)

    def claim_task(self, task_id: str, model: str) -> tuple[bool, str]:
        """Claim a task for an agent.

        Returns (success, reason) tuple.
        """
        task = self.tasks.get(task_id)
        if not task:
            return False, "task_not_found"

        if task.status != TaskState.QUEUED or task.owner_model:
            return False, "not_available"

        # Check dependencies
        deps_ok = all(
            dep in self.tasks and self.tasks[dep].status == TaskState.COMPLETED
            for dep in task.depends_on
        )
        if not deps_ok:
            return False, "dependency_not_ready"

        task.owner_model = model
        task.status = TaskState.CLAIMED
        task.claimed_at = datetime.now().isoformat()

        # Persist to storage
        if self.storage:
            self.storage.upsert_task(task_id, {
                "owner_model": model,
                "status": task.status.value,
                "claimed_at": task.claimed_at,
            })

        if self._on_task_claimed:
            self._on_task_claimed(task_id, model)

        return True, "success"

    def start_task(self, task_id: str, model: str) -> tuple[bool, str]:
        """Mark a task as started.

        Returns (success, reason) tuple.
        """
        task = self.tasks.get(task_id)
        if not task or task.owner_model != model or task.status != TaskState.CLAIMED:
            return False, "start_denied"

        task.status = TaskState.WORKING

        # Persist to storage
        if self.storage:
            self.storage.upsert_task(task_id, {"status": task.status.value})

        return True, "success"

    def complete_task(
        self, task_id: str, model: str, approved_by: str = None, summary: str = ""
    ) -> tuple[bool, str]:
        """Mark a task as completed.

        Returns (success, reason) tuple.
        """
        task = self.tasks.get(task_id)
        if not task:
            return False, "task_not_found"

        # Check critic requirement
        if task.critic_required:
            if not approved_by or approved_by == task.owner_model or approved_by not in getattr(
                self, "_agent_models", {}
            ):
                return False, "critic_required"
            task.critic_model = approved_by

        task.status = TaskState.COMPLETED
        task.completed_at = datetime.now().isoformat()

        # Persist to storage
        if self.storage:
            self.storage.upsert_task(task_id, {
                "status": task.status.value,
                "completed_at": task.completed_at,
                "result_summary": summary,
            })

        if self._on_task_completed:
            self._on_task_completed(task_id)

        return True, "success"

    def abandon_task(self, task_id: str) -> tuple[bool, str]:
        """Mark a task as abandoned.

        Returns (success, reason) tuple.
        """
        task = self.tasks.get(task_id)
        if not task:
            return False, "task_not_found"

        task.status = TaskState.ABANDONED
        task.owner_model = None

        # Persist to storage
        if self.storage:
            self.storage.upsert_task(task_id, {
                "status": task.status.value,
                "owner_model": None,
            })

        return True, "success"

    def pause_tasks_for_agent(self, model: str) -> List[str]:
        """Pause all working tasks for an agent.

        Returns list of paused task IDs.
        """
        paused = []
        for task in self.tasks.values():
            if task.owner_model == model and task.status in {
                TaskState.CLAIMED,
                TaskState.WORKING,
            }:
                task.status = TaskState.PAUSED
                paused.append(task.task_id)

                # Persist to storage
                if self.storage:
                    self.storage.upsert_task(
                        task.task_id, {"status": task.status.value, "owner_model": model}
                    )

        return paused

    def resume_tasks_for_agent(self, model: str) -> List[str]:
        """Resume all paused tasks for an agent.

        Returns list of resumed task IDs.
        """
        resumed = []
        for task in self.tasks.values():
            if task.owner_model == model and task.status == TaskState.PAUSED:
                task.status = TaskState.WORKING
                resumed.append(task.task_id)

                # Persist to storage
                if self.storage:
                    self.storage.upsert_task(
                        task.task_id, {"status": task.status.value}
                    )

        return resumed

    def abandon_tasks_for_agent(self, model: str, reason: str = "") -> List[str]:
        """Abandon all active tasks for an agent.

        Returns list of abandoned task IDs.
        """
        abandoned = []
        for task in self.tasks.values():
            if task.owner_model == model and task.status in {
                TaskState.CLAIMED,
                TaskState.WORKING,
                TaskState.PAUSED,
            }:
                task.status = TaskState.ABANDONED
                task.owner_model = None
                abandoned.append(task.task_id)

                # Persist to storage
                if self.storage:
                    self.storage.upsert_task(
                        task.task_id,
                        {"status": task.status.value, "owner_model": None},
                    )

        return abandoned

    def get_tasks_for_agent(self, model: str) -> List[TaskInfo]:
        """Get all tasks owned by an agent."""
        return [t for t in self.tasks.values() if t.owner_model == model]

    def get_active_tasks(self) -> List[TaskInfo]:
        """Get all active (claimed or working) tasks."""
        return [
            t for t in self.tasks.values()
            if t.status in {TaskState.CLAIMED, TaskState.WORKING}
        ]

    def get_queued_tasks(self) -> List[TaskInfo]:
        """Get all queued tasks sorted by priority."""
        tasks = [t for t in self.tasks.values() if t.status == TaskState.QUEUED]
        return sorted(tasks, key=lambda t: t.priority, reverse=True)

    def check_dependencies_ready(self, task: TaskInfo) -> bool:
        """Check if all dependencies for a task are completed."""
        return all(
            dep in self.tasks and self.tasks[dep].status == TaskState.COMPLETED
            for dep in task.depends_on
        )

    def serialize_task(self, task: TaskInfo) -> Dict:
        """Convert TaskInfo to dictionary."""
        return {
            "task_id": task.task_id,
            "description": task.description,
            "file": task.file,
            "operation": task.operation,
            "working_dir": task.working_dir,
            "priority": task.priority,
            "status": task.status.value,
            "owner_model": task.owner_model,
            "depends_on": task.depends_on,
            "required_capabilities": task.required_capabilities,
            "critic_required": task.critic_required,
            "critic_model": task.critic_model,
            "created_by": task.created_by,
            "created_at": task.created_at,
            "claimed_at": task.claimed_at,
            "completed_at": task.completed_at,
        }
