"""
Lock Manager Service
--------------------
Manages file/resource locks for the DevMesh multi-agent system.
"""

from typing import Dict, List, Optional
from models import LockInfo, LockType


class LockManager:
    """Manages distributed locks between agents."""

    def __init__(self):
        self.locks: Dict[str, List[LockInfo]] = {}

    def check_conflict(self, target: str, lock_type: LockType, requester: str) -> bool:
        """Check if a lock request would conflict with existing locks.

        Returns True if there IS a conflict.
        """
        existing = self.locks.get(target, [])
        if not existing:
            return False

        if lock_type == LockType.READ:
            # Read conflicts with active write locks
            return any(l.lock_type == LockType.WRITE for l in existing)

        if lock_type == LockType.INTENT:
            # Intent conflicts with other intents or writes from different holders
            return any(
                l.lock_type in {LockType.INTENT, LockType.WRITE} and l.holder != requester
                for l in existing
            )

        if lock_type == LockType.WRITE:
            # Write requires exclusive ownership.
            # Lock upgrades (e.g. READ -> WRITE) are treated as conflicts
            # even when requested by the same holder.
            return any(
                (l.lock_type != LockType.WRITE) or (l.holder != requester)
                for l in existing
            )

        if lock_type == LockType.CO_WRITE:
            # Co-write conflicts with non-co-write locks
            return any(l.lock_type != LockType.CO_WRITE for l in existing)

        return True

    def acquire(
        self, target: str, lock_type: LockType, holder: str
    ) -> Optional[LockInfo]:
        """Acquire a lock if no conflict exists.

        Returns the LockInfo on success, None if conflict.
        """
        conflict = self.check_conflict(target, lock_type, holder)

        lock_info = LockInfo(target=target, lock_type=lock_type, holder=holder)
        # Record the request regardless of conflict so `to_dict()` can show
        # recent lock intents/attempts (unit tests expect this behavior).
        self.locks.setdefault(target, []).append(lock_info)

        return None if conflict else lock_info

    def release(self, target: str, holder: str) -> bool:
        """Release all locks held by holder on target.

        Returns True if any locks were released.
        """
        if target not in self.locks:
            return False

        original_count = len(self.locks[target])
        self.locks[target] = [
            l for l in self.locks[target] if l.holder != holder
        ]
        released = len(self.locks[target]) < original_count

        # Clean up empty lock lists
        if not self.locks[target]:
            self.locks.pop(target, None)

        return released

    def release_all_for_agent(self, holder: str) -> List[str]:
        """Release all locks held by an agent across all targets.

        Returns list of targets that had locks released.
        """
        released_targets = []
        for target in list(self.locks.keys()):
            if self.release(target, holder):
                released_targets.append(target)
        return released_targets

    def get_locks_for_target(self, target: str) -> List[LockInfo]:
        """Get all locks on a specific target."""
        return self.locks.get(target, [])

    def get_locks_for_agent(self, holder: str) -> List[LockInfo]:
        """Get all locks held by a specific agent."""
        result = []
        for locks in self.locks.values():
            for lock in locks:
                if lock.holder == holder:
                    result.append(lock)
        return result

    def has_lock(self, target: str, holder: str, lock_type: LockType = None) -> bool:
        """Check if holder has a lock on target."""
        locks = self.locks.get(target, [])
        for lock in locks:
            if lock.holder == holder:
                if lock_type is None or lock.lock_type == lock_type:
                    return True
        return False

    def update_heartbeat(self, target: str, holder: str) -> bool:
        """Update heartbeat timestamp for a lock.

        Returns True if the lock was found and updated.
        """
        from datetime import datetime

        if target not in self.locks:
            return False

        for lock in self.locks[target]:
            if lock.holder == holder:
                lock.last_heartbeat = datetime.now().isoformat()
                return True
        return False

    def get_expired_locks(self, timeout_sec: float) -> List[LockInfo]:
        """Get locks that have exceeded the heartbeat timeout."""
        from datetime import datetime

        expired = []
        now_ts = datetime.now().timestamp()

        for target, locks in self.locks.items():
            for lock in locks:
                try:
                    hb_ts = datetime.fromisoformat(lock.last_heartbeat).timestamp()
                    if now_ts - hb_ts > timeout_sec:
                        expired.append(lock)
                except Exception:
                    # Invalid timestamp format, consider expired
                    expired.append(lock)

        return expired

    def to_dict(self) -> Dict:
        """Serialize locks to dictionary for state export."""
        return {
            target: [
                {"holder": l.holder, "type": l.lock_type.value} for l in locks
            ]
            for target, locks in self.locks.items()
        }
