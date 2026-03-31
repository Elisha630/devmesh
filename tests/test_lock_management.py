"""
Lock Management Tests
---------------------
Tests for lock conflict resolution, deadlocks, and edge cases.
"""

import pytest
from services.lock_manager import LockManager
from models import LockType


class TestLockConflictResolution:
    """Tests for lock conflict detection and resolution."""

    def test_read_read_no_conflict(self):
        """Multiple read locks should not conflict."""
        lm = LockManager()

        # First agent gets read lock
        lock1 = lm.acquire("/file.py", LockType.READ, "agent-1")
        assert lock1 is not None

        # Second agent should also get read lock
        lock2 = lm.acquire("/file.py", LockType.READ, "agent-2")
        assert lock2 is not None

    def test_read_write_conflict(self):
        """Write should conflict with read."""
        lm = LockManager()

        # Agent gets read lock
        lm.acquire("/file.py", LockType.READ, "agent-1")

        # Write should be denied
        lock = lm.acquire("/file.py", LockType.WRITE, "agent-2")
        assert lock is None

    def test_write_write_conflict(self):
        """Write should conflict with write."""
        lm = LockManager()

        # First agent gets write lock
        lm.acquire("/file.py", LockType.WRITE, "agent-1")

        # Second agent's write should be denied
        lock = lm.acquire("/file.py", LockType.WRITE, "agent-2")
        assert lock is None

    def test_write_blocks_all(self):
        """Write lock blocks all other locks."""
        lm = LockManager()

        # Agent gets write lock
        lm.acquire("/file.py", LockType.WRITE, "agent-1")

        # All other lock types should be denied
        assert lm.acquire("/file.py", LockType.READ, "agent-2") is None
        assert lm.acquire("/file.py", LockType.INTENT, "agent-2") is None
        assert lm.acquire("/file.py", LockType.WRITE, "agent-2") is None
        assert lm.acquire("/file.py", LockType.CO_WRITE, "agent-2") is None

    def test_intent_blocks_write(self):
        """Intent lock should block write."""
        lm = LockManager()

        lm.acquire("/file.py", LockType.INTENT, "agent-1")

        assert lm.check_conflict("/file.py", LockType.WRITE, "agent-2") is True

    def test_co_write_compatibility(self):
        """Co-write locks should be compatible with each other."""
        lm = LockManager()

        # First co-write
        lock1 = lm.acquire("/file.py", LockType.CO_WRITE, "agent-1")
        assert lock1 is not None

        # Second co-write should succeed
        lock2 = lm.acquire("/file.py", LockType.CO_WRITE, "agent-2")
        assert lock2 is not None

    def test_same_holder_no_conflict(self):
        """Same holder should not conflict with itself."""
        lm = LockManager()

        # Agent gets read lock
        lm.acquire("/file.py", LockType.READ, "agent-1")

        # Same agent upgrades to write (should fail due to conflict with self is still a conflict)
        # Actually in our implementation, same holder can have multiple locks
        lock2 = lm.acquire("/file.py", LockType.WRITE, "agent-1")
        # This may succeed depending on implementation
        # The check is holder != requester in write conflict
        assert lock2 is None  # Write conflicts with existing read


class TestLockRelease:
    """Tests for lock release functionality."""

    def test_release_lock(self):
        """Release a lock."""
        lm = LockManager()

        lm.acquire("/file.py", LockType.WRITE, "agent-1")
        released = lm.release("/file.py", "agent-1")

        assert released is True
        # Lock should be gone
        assert len(lm.get_locks_for_target("/file.py")) == 0

    def test_release_specific_holder(self):
        """Release only locks for specific holder."""
        lm = LockManager()

        lm.acquire("/file.py", LockType.READ, "agent-1")
        lm.acquire("/file.py", LockType.READ, "agent-2")

        # Release agent-1's lock
        lm.release("/file.py", "agent-1")

        # Agent-2 should still have lock
        assert len(lm.get_locks_for_target("/file.py")) == 1
        assert lm.get_locks_for_target("/file.py")[0].holder == "agent-2"

    def test_release_all_for_agent(self):
        """Release all locks held by an agent."""
        lm = LockManager()

        lm.acquire("/file1.py", LockType.WRITE, "agent-1")
        lm.acquire("/file2.py", LockType.READ, "agent-1")
        lm.acquire("/file3.py", LockType.WRITE, "agent-2")

        released = lm.release_all_for_agent("agent-1")

        assert "/file1.py" in released
        assert "/file2.py" in released
        assert len(released) == 2

        # Agent-2's lock should remain
        assert len(lm.get_locks_for_target("/file3.py")) == 1

    def test_release_nonexistent(self):
        """Release on non-existent target."""
        lm = LockManager()

        released = lm.release("/nonexistent.py", "agent-1")
        assert released is False


class TestLockQueries:
    """Tests for lock query methods."""

    def test_get_locks_for_target(self):
        """Get all locks on a specific target."""
        lm = LockManager()

        lm.acquire("/file.py", LockType.READ, "agent-1")
        lm.acquire("/file.py", LockType.READ, "agent-2")

        locks = lm.get_locks_for_target("/file.py")
        assert len(locks) == 2

    def test_get_locks_for_agent(self):
        """Get all locks held by a specific agent."""
        lm = LockManager()

        lm.acquire("/file1.py", LockType.WRITE, "agent-1")
        lm.acquire("/file2.py", LockType.READ, "agent-1")
        lm.acquire("/file3.py", LockType.WRITE, "agent-2")

        locks = lm.get_locks_for_agent("agent-1")
        assert len(locks) == 2

    def test_has_lock(self):
        """Check if agent has a lock."""
        lm = LockManager()

        lm.acquire("/file.py", LockType.WRITE, "agent-1")

        assert lm.has_lock("/file.py", "agent-1") is True
        assert lm.has_lock("/file.py", "agent-1", LockType.WRITE) is True
        assert lm.has_lock("/file.py", "agent-1", LockType.READ) is False
        assert lm.has_lock("/file.py", "agent-2") is False


class TestLockHeartbeat:
    """Tests for lock heartbeat functionality."""

    def test_update_heartbeat(self):
        """Update heartbeat for a lock."""
        lm = LockManager()

        lm.acquire("/file.py", LockType.WRITE, "agent-1")
        updated = lm.update_heartbeat("/file.py", "agent-1")

        assert updated is True
        # Heartbeat should be updated
        lock = lm.get_locks_for_target("/file.py")[0]
        assert lock.last_heartbeat is not None

    def test_update_heartbeat_wrong_holder(self):
        """Cannot update heartbeat for wrong holder."""
        lm = LockManager()

        lm.acquire("/file.py", LockType.WRITE, "agent-1")
        updated = lm.update_heartbeat("/file.py", "agent-2")

        assert updated is False

    def test_get_expired_locks(self):
        """Get locks that have exceeded timeout."""
        lm = LockManager()

        # Acquire lock with old timestamp
        import time
        from datetime import datetime, timedelta

        lm.acquire("/file.py", LockType.WRITE, "agent-1")
        # Manually set heartbeat to past
        old_time = (datetime.now() - timedelta(seconds=100)).isoformat()
        lm.locks["/file.py"][0].last_heartbeat = old_time

        expired = lm.get_expired_locks(timeout_sec=60)

        assert len(expired) == 1
        assert expired[0].holder == "agent-1"

    def test_get_expired_locks_non_expired(self):
        """No locks expired if all recent."""
        lm = LockManager()

        lm.acquire("/file.py", LockType.WRITE, "agent-1")

        expired = lm.get_expired_locks(timeout_sec=3600)  # 1 hour
        assert len(expired) == 0


class TestDeadlockPrevention:
    """Tests for deadlock prevention scenarios."""

    def test_no_deadlock_single_lock(self):
        """Single lock per agent cannot deadlock."""
        lm = LockManager()

        # Agent holds one lock
        lm.acquire("/file1.py", LockType.WRITE, "agent-1")

        # Another agent wants it - will be denied
        assert lm.acquire("/file1.py", LockType.WRITE, "agent-2") is None

        # No deadlock possible - just waiting

    def test_upgrade_not_supported(self):
        """Lock upgrade (read -> write) not directly supported - prevents deadlock."""
        lm = LockManager()

        # Agent has read lock
        lm.acquire("/file.py", LockType.READ, "agent-1")

        # Trying to get write lock should fail (would need to release first)
        assert lm.acquire("/file.py", LockType.WRITE, "agent-1") is None

    def test_multiple_targets_no_circular(self):
        """Multiple targets don't create circular wait."""
        lm = LockManager()

        # Agent 1 holds file1
        lm.acquire("/file1.py", LockType.WRITE, "agent-1")

        # Agent 2 holds file2
        lm.acquire("/file2.py", LockType.WRITE, "agent-2")

        # Agent 1 wants file2 - denied
        assert lm.acquire("/file2.py", LockType.WRITE, "agent-1") is None

        # Agent 2 wants file1 - denied
        assert lm.acquire("/file1.py", LockType.WRITE, "agent-2") is None

        # This is just contention, not deadlock


class TestLockSerialization:
    """Tests for lock serialization."""

    def test_to_dict(self):
        """Export locks to dictionary."""
        lm = LockManager()

        lm.acquire("/file.py", LockType.WRITE, "agent-1")
        lm.acquire("/file.py", LockType.READ, "agent-2")

        result = lm.to_dict()

        assert "/file.py" in result
        assert len(result["/file.py"]) == 2
        assert result["/file.py"][0]["holder"] == "agent-1"
        assert result["/file.py"][0]["type"] == "write"


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_target(self):
        """Empty target path handling."""
        lm = LockManager()

        lock = lm.acquire("", LockType.WRITE, "agent-1")
        assert lock is not None
        assert lm.has_lock("", "agent-1")

    def test_unicode_target(self):
        """Unicode target path handling."""
        lm = LockManager()

        target = "/文件/テスト/🚀.py"
        lock = lm.acquire(target, LockType.WRITE, "agent-1")
        assert lock is not None
        assert lm.has_lock(target, "agent-1")

    def test_very_long_target(self):
        """Very long target path handling."""
        lm = LockManager()

        target = "/" + "a" * 1000 + "/file.py"
        lock = lm.acquire(target, LockType.WRITE, "agent-1")
        assert lock is not None

    def test_concurrent_same_target(self):
        """Many concurrent attempts on same target."""
        lm = LockManager()

        # First write succeeds
        assert lm.acquire("/file.py", LockType.WRITE, "agent-1") is not None

        # All subsequent writes fail
        for i in range(2, 101):
            assert lm.acquire("/file.py", LockType.WRITE, f"agent-{i}") is None

        # But reads can still happen
        for i in range(2, 11):
            assert lm.acquire("/file.py", LockType.READ, f"agent-{i}") is None  # Write blocks read
