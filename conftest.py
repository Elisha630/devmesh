"""
Pytest configuration.

The test suite imports modules as top-level packages (e.g. `from services...`).
Depending on pytest's import mode, the DevMesh project root may not be present
on `sys.path`, causing intermittent `ModuleNotFoundError` during collection.

This file ensures the `devmesh/` directory is always on `sys.path` for tests.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Compatibility: some versions of the `websockets` package installed via OS
# packages don't expose `websockets.exceptions` as an attribute on the top
# module, but the code/tests reference it.
try:
    import websockets  # type: ignore
    import websockets.exceptions as _ws_exceptions  # type: ignore

    websockets.exceptions = _ws_exceptions  # type: ignore[attr-defined]
except Exception:
    pass


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    """
    Make tests deterministic by clearing shared rate-limiter state.

    The production code uses a global rate limiter singleton; without resetting,
    earlier tests can consume tokens and cause later websocket tests to fail.
    """
    try:
        from rate_limit import get_rate_limiter

        get_rate_limiter().reset()
    except Exception:
        # If rate limiting isn't available for some reason, don't block tests.
        pass

