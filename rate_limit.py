"""
DevMesh Rate Limiting Module
----------------------------
Rate limiting and throttling for API endpoints and WebSocket connections.
"""

__all__ = [
    "RateLimiter",
    "TokenBucket",
    "SlidingWindow",
    "RateLimitExceeded",
    "get_rate_limiter",
]

import time
import asyncio
from typing import Dict, Optional, Callable
from dataclasses import dataclass, field
from collections import deque
from functools import wraps


class RateLimitExceeded(Exception):
    """Rate limit has been exceeded."""

    def __init__(self, retry_after: float, limit: int, window: float):
        self.retry_after = retry_after
        self.limit = limit
        self.window = window
        super().__init__(
            f"Rate limit exceeded. Retry after {retry_after:.1f}s "
            f"(limit: {limit} per {window}s)"
        )


@dataclass
class TokenBucket:
    """
    Token bucket rate limiter.
    Allows bursts up to capacity, then rate-limited to refill rate.
    """

    capacity: int = 10
    refill_rate: float = 1.0  # tokens per second
    _tokens: float = field(default=0.0, init=False)
    _last_refill: float = field(default_factory=time.time, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self):
        self._tokens = float(self.capacity)

    async def acquire(self, tokens: float = 1.0) -> bool:
        """Try to acquire tokens. Returns True if successful."""
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_refill
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
            self._last_refill = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    async def wait(self, tokens: float = 1.0) -> None:
        """Wait until tokens are available."""
        while not await self.acquire(tokens):
            await asyncio.sleep(0.1)


@dataclass
class SlidingWindow:
    """
    Sliding window rate limiter.
    Tracks timestamps in a window and enforces a maximum count.
    """

    max_requests: int = 10
    window_seconds: float = 60.0
    _requests: deque = field(default_factory=deque, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def is_allowed(self) -> tuple[bool, int, float]:
        """
        Check if request is allowed.
        Returns (allowed, remaining, retry_after)
        """
        async with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds

            # Remove old requests outside the window
            while self._requests and self._requests[0] < cutoff:
                self._requests.popleft()

            current_count = len(self._requests)

            if current_count >= self.max_requests:
                # Calculate retry after
                oldest = self._requests[0]
                retry_after = self.window_seconds - (now - oldest)
                return False, 0, retry_after

            self._requests.append(now)
            remaining = self.max_requests - len(self._requests)
            return True, remaining, 0.0

    async def check(self) -> None:
        """Check rate limit, raise exception if exceeded."""
        allowed, _, retry_after = await self.is_allowed()
        if not allowed:
            raise RateLimitExceeded(
                retry_after=retry_after, limit=self.max_requests, window=self.window_seconds
            )


class RateLimiter:
    """
    Multi-key rate limiter with different strategies per endpoint.
    """

    def __init__(self):
        self._buckets: Dict[str, TokenBucket] = {}
        self._windows: Dict[str, SlidingWindow] = {}
        self._config: Dict[str, dict] = {
            # Default configuration for different endpoints
            "task_submit": {
                "type": "sliding_window",
                "max_requests": 30,
                "window_seconds": 60.0,
            },
            "agent_register": {
                "type": "token_bucket",
                "capacity": 5,
                "refill_rate": 0.1,  # 1 per 10 seconds
            },
            "lock_request": {
                "type": "token_bucket",
                "capacity": 100,
                "refill_rate": 10.0,
            },
            "ws_message": {
                "type": "token_bucket",
                "capacity": 1000,
                "refill_rate": 100.0,
            },
            "http_api": {
                "type": "sliding_window",
                "max_requests": 100,
                "window_seconds": 60.0,
            },
        }

    def _get_key(self, endpoint: str, identifier: str) -> str:
        """Generate unique key for rate limiter."""
        return f"{endpoint}:{identifier}"

    def _create_bucket(self, config: dict) -> TokenBucket:
        """Create a token bucket from config."""
        return TokenBucket(
            capacity=config.get("capacity", 10), refill_rate=config.get("refill_rate", 1.0)
        )

    def _create_window(self, config: dict) -> SlidingWindow:
        """Create a sliding window from config."""
        return SlidingWindow(
            max_requests=config.get("max_requests", 10),
            window_seconds=config.get("window_seconds", 60.0),
        )

    async def check(self, endpoint: str, identifier: str) -> None:
        """
        Check rate limit for an endpoint + identifier combination.

        Args:
            endpoint: The endpoint/category (e.g., "task_submit")
            identifier: The unique identifier (e.g., IP address, agent model)

        Raises:
            RateLimitExceeded: If rate limit is exceeded
        """
        key = self._get_key(endpoint, identifier)
        config = self._config.get(endpoint, self._config["http_api"])

        if config["type"] == "token_bucket":
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = self._create_bucket(config)
                self._buckets[key] = bucket

            if not await bucket.acquire():
                raise RateLimitExceeded(
                    retry_after=1.0 / config.get("refill_rate", 1.0),
                    limit=config.get("capacity", 10),
                    window=config.get("capacity", 10) / config.get("refill_rate", 1.0),
                )

        elif config["type"] == "sliding_window":
            window = self._windows.get(key)
            if window is None:
                window = self._create_window(config)
                self._windows[key] = window

            await window.check()

    async def is_allowed(self, endpoint: str, identifier: str) -> tuple[bool, int, float]:
        """
        Check if request is allowed without raising exception.

        Returns:
            Tuple of (allowed, remaining, retry_after)
        """
        key = self._get_key(endpoint, identifier)
        config = self._config.get(endpoint, self._config["http_api"])

        if config["type"] == "token_bucket":
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = self._create_bucket(config)
                self._buckets[key] = bucket

            allowed = await bucket.acquire()
            remaining = int(bucket._tokens)
            retry_after = 0.0 if allowed else 1.0 / config.get("refill_rate", 1.0)
            return allowed, remaining, retry_after

        elif config["type"] == "sliding_window":
            window = self._windows.get(key)
            if window is None:
                window = self._create_window(config)
                self._windows[key] = window

            return await window.is_allowed()

        return True, 0, 0.0

    def update_config(self, endpoint: str, config: dict) -> None:
        """Update rate limiting configuration for an endpoint."""
        self._config[endpoint] = config
        # Clear existing limiters for this endpoint
        keys_to_remove = [
            k for k in {**self._buckets, **self._windows}.keys() if k.startswith(f"{endpoint}:")
        ]
        for key in keys_to_remove:
            self._buckets.pop(key, None)
            self._windows.pop(key, None)

    def reset(self, endpoint: Optional[str] = None) -> None:
        """Reset rate limiters. If endpoint specified, only reset that endpoint."""
        if endpoint:
            keys_to_remove = [
                k for k in {**self._buckets, **self._windows}.keys() if k.startswith(f"{endpoint}:")
            ]
            for key in keys_to_remove:
                self._buckets.pop(key, None)
                self._windows.pop(key, None)
        else:
            self._buckets.clear()
            self._windows.clear()


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def rate_limit(endpoint: str, identifier_func: Optional[Callable] = None):
    """
    Decorator for rate limiting functions.

    Args:
        endpoint: The rate limit endpoint category
        identifier_func: Optional function to extract identifier from args
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            limiter = get_rate_limiter()

            # Extract identifier
            if identifier_func:
                identifier = identifier_func(*args, **kwargs)
            else:
                # Default: use first arg if it's a string (likely model/IP)
                identifier = str(args[0]) if args else "default"

            await limiter.check(endpoint, identifier)
            return await func(*args, **kwargs)

        # Attach rate limiter methods to function for testing
        wrapper.rate_limiter = limiter
        return wrapper

    return decorator
