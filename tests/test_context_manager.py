"""
Unit tests for `services.context_manager.ContextManager`.

These tests focus on conflict detection, diff/content tracking, and the
storage persistence hook.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from services.context_manager import ContextManager


def test_update_file_creates_and_increments_version():
    cm = ContextManager()

    r1 = cm.update_file(path="/a.py", model="m1", content="v1")
    assert r1["version"] == 1
    assert r1["conflict"] is False

    r2 = cm.update_file(path="/a.py", model="m1", content="v2")
    assert r2["version"] == 2
    assert cm.get_content("/a.py") == "v2"
    assert cm.get_diffs("/a.py") == []


def test_update_file_conflict_detection_and_callback_cooldown():
    cm = ContextManager(conflict_cooldown_sec=10.0)
    cb = MagicMock()
    cm.set_conflict_callback(cb)

    cm.update_file(path="/a.py", model="m1", content="v1")
    r2 = cm.update_file(path="/a.py", model="m2", content="v2")
    assert r2["conflict"] is True
    assert r2["previous_writer"] == "m1"
    assert cb.call_count == 1
    cb.assert_called_with("/a.py", "m2", "m1")

    # Another conflicting write within cooldown should not trigger callback again.
    r3 = cm.update_file(path="/a.py", model="m1", content="v3")
    assert r3["conflict"] is True
    assert r3["previous_writer"] == "m2"
    assert cb.call_count == 1

    assert cm.is_conflict_window_active("/a.py") is True


def test_update_file_tracks_diffs_and_get_recent_entries():
    cm = ContextManager()

    cm.update_file(path="/a.py", model="m1", diff="d1", content="c1")
    time.sleep(0.01)
    cm.update_file(path="/b.py", model="m1", diff="d2", content="c2")

    assert cm.get_diffs("/a.py") == ["d1"]
    assert cm.get_diffs("/b.py") == ["d2"]

    recent = cm.get_recent_entries(limit=2)
    assert {e["path"] for e in recent} == {"/a.py", "/b.py"}


def test_save_to_storage_persists_truncated_content():
    storage = MagicMock()
    cm = ContextManager(storage=storage)

    long_content = "x" * 5000
    cm.update_file(path="/big.txt", model="m2", content=long_content)

    ok = cm.save_to_storage("/big.txt")
    assert ok is True
    storage.add_context_item.assert_called_once()
    kwargs = storage.add_context_item.call_args.kwargs
    assert kwargs["key"] == "file:/big.txt"
    assert kwargs["source_agent"] == "m2"
    assert kwargs["confidence"] == 1.0
    assert len(kwargs["value"]) == 4000


def test_get_file_info_clear_and_get_entry():
    cm = ContextManager()
    cm.update_file(path="/a.py", model="m1", content="v1", diff="d1")

    info = cm.get_file_info("/a.py")
    assert info is not None
    assert info["path"] == "/a.py"
    assert info["diff_count"] == 1

    assert cm.get_entry("/a.py") is not None
    assert cm.clear_path("/a.py") is True
    assert cm.get_entry("/a.py") is None

