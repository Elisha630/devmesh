"""
DevMesh File Watching Service
-----------------------------
Real file system watching with debounce and change aggregation.
"""

import asyncio
import time
from pathlib import Path
from typing import Dict, Optional, Set, Callable, Any
from dataclasses import dataclass
from datetime import datetime
import logging

try:
    from watchfiles import watch, DefaultFilter

    WATCHFILES_AVAILABLE = True
except ImportError:
    WATCHFILES_AVAILABLE = False

log = logging.getLogger("devmesh.file_watching")


__all__ = [
    "FileChangeEvent",
    "FileWatcher",
    "get_file_watcher",
]


@dataclass
class FileChangeEvent:
    """Represents a file change event."""

    path: Path
    change_type: str  # 'created', 'modified', 'deleted'
    timestamp: str
    size: Optional[int] = None

    def __hash__(self):
        return hash((str(self.path), self.change_type))

    def __eq__(self, other):
        if not isinstance(other, FileChangeEvent):
            return False
        return self.path == other.path and self.change_type == other.change_type


class FileWatcher:
    """Watches file system for changes with debouncing."""

    def __init__(self, debounce_sec: float = 1.0):
        self.debounce_sec = debounce_sec
        self.watched_paths: Set[Path] = set()
        self.callbacks: Dict[str, Callable] = {}
        self._pending_changes: Dict[str, Set[FileChangeEvent]] = {}
        self._debounce_tasks: Dict[str, asyncio.Task] = {}
        self._watch_task: Optional[asyncio.Task] = None
        self._running = False

    def watch(self, path: str, callback: Optional[Callable] = None) -> None:
        """Watch a directory or file for changes."""
        watch_path = Path(path)

        if not watch_path.exists():
            log.warning(f"Watch path does not exist: {watch_path}")
            return

        if watch_path not in self.watched_paths:
            self.watched_paths.add(watch_path)
            log.info(f"Watching: {watch_path}")

        if callback:
            callback_name = f"{watch_path}:{id(callback)}"
            self.callbacks[callback_name] = callback

    def unwatch(self, path: str) -> None:
        """Stop watching a path."""
        watch_path = Path(path)
        self.watched_paths.discard(watch_path)

        # Remove callbacks for this path
        keys_to_remove = [k for k in self.callbacks if k.startswith(str(watch_path))]
        for key in keys_to_remove:
            del self.callbacks[key]

        log.info(f"Unwatched: {watch_path}")

    def register_callback(self, callback: Callable) -> None:
        """Register a callback for all watched paths."""
        callback_name = f"global:{id(callback)}"
        self.callbacks[callback_name] = callback

    async def _watch_loop(self) -> None:
        """Main loop that monitors file changes."""
        if not WATCHFILES_AVAILABLE:
            log.warning("watchfiles not available; file watching disabled")
            return

        while self._running:
            try:
                if not self.watched_paths:
                    await asyncio.sleep(0.5)
                    continue

                # Use watchfiles to monitor changes
                for changes in watch(*self.watched_paths, watch_filter=DefaultFilter()):
                    for change_type, path in changes:
                        await self._handle_change(path, change_type)

            except Exception as e:
                log.error(f"Error in file watch loop: {e}")
                await asyncio.sleep(1)

    async def _handle_change(self, path: str, change_type: int) -> None:
        """Handle a file change with debouncing."""
        file_path = Path(path)

        # Map watchfiles change types to our types
        type_map = {
            1: "modified",  # Change
            2: "deleted",  # Deleted
            3: "created",  # Created
        }
        change_name = type_map.get(change_type, "modified")

        event = FileChangeEvent(
            path=file_path,
            change_type=change_name,
            timestamp=datetime.now().isoformat(),
            size=file_path.stat().st_size if file_path.exists() else None,
        )

        # Add to pending changes for debouncing
        event_key = str(file_path)
        self._pending_changes.setdefault(event_key, set()).add(event)

        # Cancel existing debounce task for this path
        if event_key in self._debounce_tasks:
            self._debounce_tasks[event_key].cancel()

        # Create new debounce task
        self._debounce_tasks[event_key] = asyncio.create_task(self._debounce_and_notify(event_key))

    async def _debounce_and_notify(self, event_key: str) -> None:
        """Debounce changes and notify callbacks."""
        try:
            await asyncio.sleep(self.debounce_sec)

            if event_key in self._pending_changes:
                changes = self._pending_changes.pop(event_key)

                # Notify all callbacks
                for callback in self.callbacks.values():
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(list(changes))
                        else:
                            callback(list(changes))
                    except Exception as e:
                        log.error(f"Error in file watch callback: {e}")

        except asyncio.CancelledError:
            pass  # Task was cancelled, that's expected
        finally:
            self._debounce_tasks.pop(event_key, None)

    async def start(self) -> None:
        """Start watching files."""
        if self._running:
            return

        self._running = True
        if WATCHFILES_AVAILABLE:
            self._watch_task = asyncio.create_task(self._watch_loop())
            log.info("File watcher started")

    async def stop(self) -> None:
        """Stop watching files."""
        self._running = False

        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass

        # Cancel all pending debounce tasks
        for task in self._debounce_tasks.values():
            task.cancel()

        self._debounce_tasks.clear()
        log.info("File watcher stopped")


# Global file watcher instance
_file_watcher: Optional[FileWatcher] = None


def get_file_watcher(debounce_sec: float = 1.0) -> FileWatcher:
    """Get the global file watcher instance."""
    global _file_watcher
    if _file_watcher is None:
        _file_watcher = FileWatcher(debounce_sec)
    return _file_watcher
