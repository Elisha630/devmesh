"""
Context Manager Service
-------------------------
Manages file context buffer and conflict detection for DevMesh.
"""

import time
from typing import Dict, List, Optional, Callable, Any
from pathlib import Path
from models import ContextBufferEntry


class ContextManager:
    """Manages file context and conflict detection."""

    def __init__(self, storage=None, conflict_cooldown_sec: float = 10.0):
        self.contexts: Dict[str, ContextBufferEntry] = {}
        self.storage = storage
        self.conflict_cooldown_sec = conflict_cooldown_sec
        self._conflict_resolve_guard: Dict[str, float] = {}
        self._on_conflict: Optional[Callable[[str, str, str], Any]] = None

    def set_conflict_callback(self, callback: Callable[[str, str, str], Any]):
        """Set callback for conflict events.

        Args:
            callback: Function called with (path, current_writer, previous_writer)
        """
        self._on_conflict = callback

    def get_or_create_entry(self, path: str) -> ContextBufferEntry:
        """Get existing context entry or create new one."""
        if path not in self.contexts:
            self.contexts[path] = ContextBufferEntry(file_path=path, content="")
        return self.contexts[path]

    def update_file(
        self,
        path: str,
        model: str,
        content: str = "",
        diff: str = "",
        operation: str = "write",
    ) -> Dict:
        """Update file in context buffer.

        Returns dict with keys:
            - version: int
            - conflict: bool
            - previous_writer: str or None
        """
        entry = self.get_or_create_entry(path)
        conflict_detected = False
        previous_writer = None

        # Conflict Detection
        if entry.last_writer and entry.last_writer != model:
            # If someone else wrote within the conflict window (5 seconds)
            if time.time() - entry.last_updated < 5.0:
                previous_writer = entry.last_writer
                conflict_detected = True

                # Trigger conflict callback if not in cooldown
                guard_ts = self._conflict_resolve_guard.get(path)
                now_ts = time.time()
                if not guard_ts or (now_ts - guard_ts) > self.conflict_cooldown_sec:
                    self._conflict_resolve_guard[path] = now_ts
                    if self._on_conflict:
                        self._on_conflict(path, model, previous_writer)

        # Update entry
        entry.version += 1
        entry.last_updated = time.time()
        entry.last_writer = model
        if content:
            entry.content = content
        if diff:
            entry.diffs.append(diff)

        return {
            "version": entry.version,
            "conflict": conflict_detected,
            "previous_writer": previous_writer,
        }

    def get_content(self, path: str) -> Optional[str]:
        """Get current content for a file path."""
        entry = self.contexts.get(path)
        return entry.content if entry else None

    def get_diffs(self, path: str, limit: int = 5) -> List[str]:
        """Get recent diffs for a file path."""
        entry = self.contexts.get(path)
        if entry and entry.diffs:
            return entry.diffs[-limit:]
        return []

    def get_entry(self, path: str) -> Optional[ContextBufferEntry]:
        """Get full context entry for a path."""
        return self.contexts.get(path)

    def get_all_paths(self) -> List[str]:
        """Get all paths in context buffer."""
        return list(self.contexts.keys())

    def clear_path(self, path: str) -> bool:
        """Remove a path from context buffer.

        Returns True if path existed and was removed.
        """
        if path in self.contexts:
            del self.contexts[path]
            return True
        return False

    def save_to_storage(self, path: str) -> bool:
        """Persist current context to storage.

        Returns True if saved successfully.
        """
        if not self.storage:
            return False

        entry = self.contexts.get(path)
        if not entry:
            return False

        try:
            self.storage.add_context_item(
                key=f"file:{path}",
                value=entry.content[:4000],  # Truncate for storage
                source_agent=entry.last_writer or "unknown",
                confidence=1.0,
            )
            return True
        except Exception:
            return False

    def get_file_info(self, path: str) -> Optional[Dict]:
        """Get file info including version, last writer, etc."""
        entry = self.contexts.get(path)
        if not entry:
            return None

        return {
            "path": path,
            "version": entry.version,
            "last_updated": entry.last_updated,
            "last_writer": entry.last_writer,
            "content_length": len(entry.content),
            "diff_count": len(entry.diffs),
        }

    def is_conflict_window_active(self, path: str) -> bool:
        """Check if file is in conflict resolution window."""
        guard_ts = self._conflict_resolve_guard.get(path)
        if not guard_ts:
            return False
        return time.time() - guard_ts < self.conflict_cooldown_sec

    def get_recent_entries(self, limit: int = 20) -> List[Dict]:
        """Get most recently updated entries."""
        sorted_entries = sorted(
            self.contexts.values(),
            key=lambda e: e.last_updated,
            reverse=True,
        )
        return [
            {
                "path": e.file_path,
                "version": e.version,
                "last_updated": e.last_updated,
                "last_writer": e.last_writer,
            }
            for e in sorted_entries[:limit]
        ]
