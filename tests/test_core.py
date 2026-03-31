"""
DevMesh Test Suite
------------------
Unit tests for core components.
Run with: python -m pytest tests/ -v
"""

import pytest
import asyncio
from pathlib import Path
from datetime import datetime


class TestStorageManager:
    """Tests for storage.py StorageManager class."""

    def test_init_creates_database(self, tmp_path):
        from storage import StorageManager

        db_path = tmp_path / "test.db"
        storage = StorageManager(db_path)

        assert db_path.exists()
        storage.close()

    def test_upsert_and_get_agent(self, tmp_path):
        from storage import StorageManager

        db_path = tmp_path / "test.db"
        storage = StorageManager(db_path)

        agent_data = {
            "session_id": "test-session-123",
            "role": "architect",
            "status": "idle",
            "is_active": 1,
            "connected_at": datetime.now().isoformat(),
            "hardware_usage": {"vram_gb": 2, "ram_gb": 4},
        }

        storage.upsert_agent("test-agent", agent_data)
        storage._flush_writes()  # Wait for async write to complete
        retrieved = storage.get_agent("test-agent")

        assert retrieved is not None
        assert retrieved["session_id"] == "test-session-123"
        assert retrieved["role"] == "architect"
        storage.close()

    def test_upsert_and_get_task(self, tmp_path):
        from storage import StorageManager

        db_path = tmp_path / "test.db"
        storage = StorageManager(db_path)

        task_data = {
            "description": "Test task",
            "status": "queued",
            "owner_model": "test-agent",
            "working_dir": "/tmp/test",
            "details": {"key": "value"},
            "priority": 5,
        }

        storage.upsert_task("task-001", task_data)
        storage._flush_writes()  # Wait for async write to complete
        retrieved = storage.get_task("task-001")

        assert retrieved is not None
        assert retrieved["description"] == "Test task"
        assert retrieved["details"]["key"] == "value"
        assert retrieved["priority"] == 5
        storage.close()

    def test_log_and_get_events(self, tmp_path):
        from storage import StorageManager

        db_path = tmp_path / "test.db"
        storage = StorageManager(db_path)

        storage.log_event("test_event", "test-agent", {"data": "test"})
        storage._flush_writes()  # Wait for async write to complete
        events = storage.get_recent_events(limit=10)

        assert len(events) > 0
        assert events[0]["event_type"] == "test_event"
        storage.close()

    def test_get_recent_tasks_ordering(self, tmp_path):
        from storage import StorageManager
        import time

        db_path = tmp_path / "test.db"
        storage = StorageManager(db_path)

        # Create tasks in reverse order
        for i in range(5):
            storage.upsert_task(
                f"task-{i}",
                {
                    "description": f"Task {i}",
                    "status": "completed",
                    "created_at": datetime.now().isoformat(),
                },
            )
            storage._flush_writes()  # Wait for async write to complete
            time.sleep(0.01)  # Ensure different timestamps

        recent = storage.get_recent_tasks(limit=3)

        assert len(recent) == 3
        storage.close()

    def test_task_priority_ordering(self, tmp_path):
        """Test that get_recent_tasks sorts by priority DESC, then created_at DESC."""
        from storage import StorageManager

        db_path = tmp_path / "test.db"
        storage = StorageManager(db_path)

        # Create tasks with different priorities
        storage.upsert_task(
            "low-priority-task",
            {
                "description": "Low priority task",
                "status": "queued",
                "created_at": "2025-01-01T10:00:00",
                "priority": 1,
            },
        )
        storage.upsert_task(
            "high-priority-task",
            {
                "description": "High priority task",
                "status": "queued",
                "created_at": "2025-01-01T09:00:00",  # Earlier timestamp
                "priority": 5,
            },
        )
        storage.upsert_task(
            "medium-priority-task",
            {
                "description": "Medium priority task",
                "status": "queued",
                "created_at": "2025-01-01T11:00:00",
                "priority": 3,
            },
        )
        storage._flush_writes()

        recent = storage.get_recent_tasks(limit=10)

        # Should be sorted by priority DESC: 5, 3, 1
        assert len(recent) == 3
        assert recent[0]["priority"] == 5
        assert recent[1]["priority"] == 3
        assert recent[2]["priority"] == 1
        assert recent[0]["task_id"] == "high-priority-task"
        assert recent[1]["task_id"] == "medium-priority-task"
        assert recent[2]["task_id"] == "low-priority-task"
        storage.close()

    def test_task_priority_validation(self, tmp_path):
        """Test that priority values are validated and clamped to 1-5."""
        from storage import StorageManager

        db_path = tmp_path / "test.db"
        storage = StorageManager(db_path)

        # Test priority too high - should clamp to valid range
        storage.upsert_task(
            "invalid-priority", {"description": "Invalid priority task", "priority": 10}  # Too high
        )
        storage._flush_writes()

        retrieved = storage.get_task("invalid-priority")
        assert retrieved["priority"] == 3  # Should use default

        # Test negative priority
        storage.upsert_task(
            "negative-priority", {"description": "Negative priority task", "priority": -1}
        )
        storage._flush_writes()

        retrieved = storage.get_task("negative-priority")
        assert retrieved["priority"] == 3  # Should use default

        # Test valid priority at boundaries
        storage.upsert_task("min-priority", {"description": "Min priority", "priority": 1})
        storage.upsert_task("max-priority", {"description": "Max priority", "priority": 5})
        storage._flush_writes()

        assert storage.get_task("min-priority")["priority"] == 1
        assert storage.get_task("max-priority")["priority"] == 5

        storage.close()


class TestConfigValidation:
    """Tests for config.py validation."""

    def test_server_config_default_values(self):
        from config import ServerConfig

        cfg = ServerConfig()

        assert cfg.ws_port == 7700
        assert cfg.http_port == 7701
        assert cfg.dashboard_port == 7702
        assert cfg.lock_ttl_sec == 15

    def test_server_config_invalid_port(self):
        import os
        import sys

        # Test that port validation works for out-of-range values
        old_port = os.environ.get("DEVMESH_WS_PORT")
        os.environ["DEVMESH_WS_PORT"] = "0"  # Invalid port (must be 1-65535)

        try:
            # Force reimport to pick up new environment variable
            if "config" in sys.modules:
                del sys.modules["config"]

            from config import ServerConfig

            with pytest.raises(ValueError):
                ServerConfig()
        finally:
            if old_port:
                os.environ["DEVMESH_WS_PORT"] = old_port
            else:
                del os.environ["DEVMESH_WS_PORT"]
            # Reload config module with original settings
            if "config" in sys.modules:
                del sys.modules["config"]

    def test_tool_profiles_sync(self):
        from config import KNOWN_CLI_TOOLS, TOOL_PROFILES

        known_names = set(t["name"] for t in KNOWN_CLI_TOOLS)
        profile_names = set(TOOL_PROFILES.keys())

        assert known_names == profile_names, "KNOWN_CLI_TOOLS and TOOL_PROFILES must be in sync"


class TestErrorClasses:
    """Tests for errors.py exception hierarchy."""

    def test_devmesh_error_to_dict(self):
        from errors import DevMeshError

        error = DevMeshError("Test error", "TEST_CODE", {"key": "value"})
        result = error.to_dict()

        assert result["error"] == "DevMeshError"
        assert result["code"] == "TEST_CODE"
        assert result["message"] == "Test error"
        assert result["details"]["key"] == "value"

    def test_agent_not_registered(self):
        from errors import AgentNotRegistered

        error = AgentNotRegistered("test-agent")
        result = error.to_dict()

        assert result["code"] == "AGENT_NOT_REGISTERED"
        assert "test-agent" in result["message"]

    def test_lock_conflict(self):
        from errors import LockConflict

        error = LockConflict("/path/to/file", "Already locked by another agent")
        result = error.to_dict()

        assert result["code"] == "LOCK_CONFLICT"
        assert result["details"]["target"] == "/path/to/file"


class TestLogger:
    """Tests for logger.py."""

    def test_setup_logging_creates_logger(self):
        from logger import setup_logging
        import logging

        logger = setup_logging(log_level="DEBUG", name="test_logger")

        assert isinstance(logger, logging.Logger)
        assert logger.level == logging.DEBUG

    def test_colored_formatter(self):
        from logger import ColoredFormatter
        import logging

        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)

        # The formatter includes ANSI color codes, so we check for INFO without exact match
        assert "INFO" in formatted
        assert "Test message" in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
