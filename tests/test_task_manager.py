"""
Task Manager Tests
------------------
Tests for task lifecycle, priorities, and dependencies.
"""

import pytest
from services.task_manager import TaskManager
from models import TaskState, TaskInfo


class TestTaskCreation:
    """Tests for task creation."""

    def test_create_basic_task(self):
        """Create a basic task."""
        tm = TaskManager()

        task = tm.create_task(
            task_id="task-1", description="Test task", file="test.py", operation="create"
        )

        assert task is not None
        assert task.task_id == "task-1"
        assert task.description == "Test task"
        assert task.status == TaskState.QUEUED

    def test_create_duplicate_task_id(self):
        """Cannot create task with duplicate ID."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="First")
        task2 = tm.create_task(task_id="task-1", description="Second")

        assert task2 is None

    def test_create_task_with_priority(self):
        """Create task with priority."""
        tm = TaskManager()

        task = tm.create_task(task_id="task-1", description="High priority", priority=5)

        assert task.priority == 5


class TestTaskLifecycle:
    """Tests for task state transitions."""

    def test_claim_task(self):
        """Claim a queued task."""
        tm = TaskManager()

        task = tm.create_task(task_id="task-1", description="Test")
        success, reason = tm.claim_task("task-1", "agent-1")

        assert success is True
        assert task.status == TaskState.CLAIMED
        assert task.owner_model == "agent-1"

    def test_claim_already_claimed(self):
        """Cannot claim an already claimed task."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="Test")
        tm.claim_task("task-1", "agent-1")

        success, reason = tm.claim_task("task-1", "agent-2")
        assert success is False
        assert "not_available" in reason

    def test_start_task(self):
        """Start a claimed task."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="Test")
        tm.claim_task("task-1", "agent-1")
        success, reason = tm.start_task("task-1", "agent-1")

        assert success is True
        assert reason == "success"
        assert tm.get_task("task-1").status == TaskState.WORKING

    def test_complete_task(self):
        """Complete a working task."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="Test")
        tm.claim_task("task-1", "agent-1")
        tm.start_task("task-1", "agent-1")
        success, reason = tm.complete_task("task-1", "agent-1")

        assert success is True
        assert tm.get_task("task-1").status == TaskState.COMPLETED

    def test_abandon_task(self):
        """Abandon a task."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="Test")
        tm.claim_task("task-1", "agent-1")
        success, reason = tm.abandon_task("task-1")

        assert success is True
        assert tm.get_task("task-1").status == TaskState.ABANDONED
        assert tm.get_task("task-1").owner_model is None


class TestTaskDependencies:
    """Tests for task dependencies."""

    def test_claim_with_unsatisfied_dependencies(self):
        """Cannot claim task with incomplete dependencies."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="First")
        tm.create_task(task_id="task-2", description="Second", depends_on=["task-1"])

        success, reason = tm.claim_task("task-2", "agent-1")

        assert success is False
        assert "dependency" in reason

    def test_claim_with_satisfied_dependencies(self):
        """Can claim task when dependencies completed."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="First")
        tm.create_task(task_id="task-2", description="Second", depends_on=["task-1"])

        # Complete first task
        tm.claim_task("task-1", "agent-1")
        tm.start_task("task-1", "agent-1")
        tm.complete_task("task-1", "agent-1")

        # Now second task should be claimable
        success, reason = tm.claim_task("task-2", "agent-2")
        assert success is True

    def test_check_dependencies_ready(self):
        """Check if all dependencies are ready."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="First")
        task2 = tm.create_task(task_id="task-2", description="Second", depends_on=["task-1"])

        assert tm.check_dependencies_ready(task2) is False

        tm.claim_task("task-1", "agent-1")
        tm.start_task("task-1", "agent-1")
        tm.complete_task("task-1", "agent-1")

        assert tm.check_dependencies_ready(task2) is True


class TestTaskPriority:
    """Tests for task priority queue behavior."""

    def test_get_queued_tasks_sorted(self):
        """Queued tasks sorted by priority."""
        tm = TaskManager()

        tm.create_task(task_id="low", description="Low", priority=1)
        tm.create_task(task_id="high", description="High", priority=5)
        tm.create_task(task_id="medium", description="Medium", priority=3)

        queued = tm.get_queued_tasks()

        assert len(queued) == 3
        assert queued[0].task_id == "high"
        assert queued[1].task_id == "medium"
        assert queued[2].task_id == "low"

    def test_same_priority_ordering(self):
        """Tasks with same priority maintain creation order."""
        tm = TaskManager()

        tm.create_task(task_id="first", description="First", priority=1)
        tm.create_task(task_id="second", description="Second", priority=1)

        queued = tm.get_queued_tasks()

        assert queued[0].task_id == "first"
        assert queued[1].task_id == "second"


class TestTaskPauseResume:
    """Tests for pausing and resuming tasks."""

    def test_pause_tasks_for_agent(self):
        """Pause all tasks for an agent."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="Task 1")
        tm.create_task(task_id="task-2", description="Task 2")
        tm.claim_task("task-1", "agent-1")
        tm.claim_task("task-2", "agent-1")
        tm.start_task("task-1", "agent-1")
        tm.start_task("task-2", "agent-1")

        paused = tm.pause_tasks_for_agent("agent-1")

        assert len(paused) == 2
        assert tm.get_task("task-1").status == TaskState.PAUSED
        assert tm.get_task("task-2").status == TaskState.PAUSED

    def test_resume_tasks_for_agent(self):
        """Resume paused tasks for an agent."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="Task 1")
        tm.claim_task("task-1", "agent-1")
        tm.start_task("task-1", "agent-1")
        tm.pause_tasks_for_agent("agent-1")

        resumed = tm.resume_tasks_for_agent("agent-1")

        assert len(resumed) == 1
        assert tm.get_task("task-1").status == TaskState.WORKING

    def test_abandon_tasks_for_agent(self):
        """Abandon all active tasks for an agent."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="Task 1")
        tm.create_task(task_id="task-2", description="Task 2")
        tm.claim_task("task-1", "agent-1")
        tm.claim_task("task-2", "agent-1")

        abandoned = tm.abandon_tasks_for_agent("agent-1")

        assert len(abandoned) == 2
        assert tm.get_task("task-1").status == TaskState.ABANDONED
        assert tm.get_task("task-2").status == TaskState.ABANDONED


class TestTaskQueries:
    """Tests for task query methods."""

    def test_get_tasks_for_agent(self):
        """Get all tasks owned by an agent."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="Task 1")
        tm.create_task(task_id="task-2", description="Task 2")
        tm.claim_task("task-1", "agent-1")
        tm.claim_task("task-2", "agent-2")

        agent1_tasks = tm.get_tasks_for_agent("agent-1")

        assert len(agent1_tasks) == 1
        assert agent1_tasks[0].task_id == "task-1"

    def test_get_active_tasks(self):
        """Get all active (claimed or working) tasks."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="Task 1")
        tm.create_task(task_id="task-2", description="Task 2")
        tm.create_task(task_id="task-3", description="Task 3")

        tm.claim_task("task-1", "agent-1")
        tm.claim_task("task-2", "agent-1")
        tm.start_task("task-2", "agent-1")
        # task-3 remains queued

        active = tm.get_active_tasks()

        assert len(active) == 2
        assert all(t.status in [TaskState.CLAIMED, TaskState.WORKING] for t in active)

    def test_serialize_task(self):
        """Convert task to dictionary."""
        tm = TaskManager()

        task = tm.create_task(task_id="task-1", description="Test task", file="test.py", priority=3)

        serialized = tm.serialize_task(task)

        assert serialized["task_id"] == "task-1"
        assert serialized["description"] == "Test task"
        assert serialized["status"] == TaskState.QUEUED.value
        assert serialized["priority"] == 3


class TestTaskCallbacks:
    """Tests for task event callbacks."""

    def test_task_created_callback(self):
        """Callback called on task creation."""
        tm = TaskManager()
        created_tasks = []

        def on_created(task):
            created_tasks.append(task.task_id)

        tm.set_callbacks(on_task_created=on_created)
        tm.create_task(task_id="task-1", description="Test")

        assert len(created_tasks) == 1
        assert created_tasks[0] == "task-1"

    def test_task_claimed_callback(self):
        """Callback called on task claim."""
        tm = TaskManager()
        claimed_events = []

        def on_claimed(task_id, model):
            claimed_events.append((task_id, model))

        tm.set_callbacks(on_task_claimed=on_claimed)
        tm.create_task(task_id="task-1", description="Test")
        tm.claim_task("task-1", "agent-1")

        assert len(claimed_events) == 1
        assert claimed_events[0] == ("task-1", "agent-1")

    def test_task_completed_callback(self):
        """Callback called on task completion."""
        tm = TaskManager()
        completed_tasks = []

        def on_completed(task_id):
            completed_tasks.append(task_id)

        tm.set_callbacks(on_task_completed=on_completed)
        tm.create_task(task_id="task-1", description="Test")
        tm.claim_task("task-1", "agent-1")
        tm.start_task("task-1", "agent-1")
        tm.complete_task("task-1", "agent-1")

        assert len(completed_tasks) == 1
        assert completed_tasks[0] == "task-1"


class TestTaskEdgeCases:
    """Edge case tests for task manager."""

    def test_circular_dependencies(self):
        """Handle circular dependencies gracefully."""
        tm = TaskManager()

        # Create tasks that depend on each other
        task1 = tm.create_task(task_id="task-1", description="First", depends_on=["task-2"])
        task2 = tm.create_task(task_id="task-2", description="Second", depends_on=["task-1"])

        # Neither should be claimable
        assert tm.check_dependencies_ready(task1) is False
        assert tm.check_dependencies_ready(task2) is False

    def test_nonexistent_dependency(self):
        """Task with non-existent dependency."""
        tm = TaskManager()

        task = tm.create_task(task_id="task-1", description="Test", depends_on=["nonexistent"])

        assert tm.check_dependencies_ready(task) is False

    def test_empty_task_id(self):
        """Task with empty ID."""
        tm = TaskManager()

        task = tm.create_task(task_id="", description="Test")

        assert task is not None
        assert task.task_id == ""

    def test_very_long_description(self):
        """Task with very long description."""
        tm = TaskManager()

        long_desc = "A" * 10000
        task = tm.create_task(task_id="task-1", description=long_desc)

        assert task.description == long_desc

    def test_many_tasks(self):
        """Create many tasks."""
        tm = TaskManager()

        for i in range(1000):
            tm.create_task(task_id=f"task-{i}", description=f"Task {i}")

        assert len(tm.tasks) == 1000

    def test_claim_same_task_by_many(self):
        """Many agents try to claim same task."""
        tm = TaskManager()

        tm.create_task(task_id="task-1", description="Test")

        # First claim succeeds
        success1, _ = tm.claim_task("task-1", "agent-1")
        assert success1 is True

        # Rest fail
        for i in range(2, 100):
            success, _ = tm.claim_task("task-1", f"agent-{i}")
            assert success is False
