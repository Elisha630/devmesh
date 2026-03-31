"""
Local `orjson` shim (dev/test fallback).

The upstream project uses the compiled `orjson` package for speed. In some
environments (like this execution sandbox) the binary wheel may be unavailable.
This module provides a minimal compatible surface used by DevMesh:
  - dumps(obj) -> bytes
  - loads(bytes|str) -> object
  - JSONDecodeError exception type

It is intentionally small and not a full orjson replacement.
"""

from __future__ import annotations

import json
from typing import Any


JSONDecodeError = json.JSONDecodeError


def dumps(obj: Any, *args: Any, **kwargs: Any) -> bytes:
    """
    Serialize `obj` to JSON and return UTF-8 bytes.

    DevMesh only uses `dumps()` without advanced `orjson` options.
    """
    # Use compact representation similar to orjson defaults.
    separators = kwargs.pop("option", None)  # ignored, kept for signature-compat
    _ = separators
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def loads(data: bytes | str, *args: Any, **kwargs: Any) -> Any:
    """Deserialize JSON from bytes or string."""
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    return json.loads(data)

