"""
DevMesh Resilience Module
-------------------------
Circuit breaker, retry logic, and resilience patterns for DevMesh.
"""

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpen",
    "retry_with_backoff",
    "RetryExhausted",
    "HealthChecker",
    "ServiceHealth",
]

import asyncio
import time
import functools
import logging
import subprocess
from enum import Enum
from typing import Callable, Optional, Any, Dict, List
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger("devmesh.resilience")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreakerOpen(Exception):
    """Circuit breaker is open, rejecting requests."""

    def __init__(self, service: str, retry_after: float):
        self.service = service
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker open for '{service}'. "
            f"Retry after {retry_after:.1f}s"
        )


class RetryExhausted(Exception):
    """All retry attempts exhausted."""

    def __init__(self, message: str, attempts: int, last_error: Exception):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"{message} after {attempts} attempts: {last_error}")


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5          # Failures before opening
    recovery_timeout: float = 30.0       # Seconds before half-open
    half_open_max_calls: int = 3         # Test calls in half-open
    success_threshold: int = 2           # Successes to close


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.

    Prevents cascading failures by stopping requests to failing services.
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.successes = 0
        self.last_failure_time: Optional[float] = None
        self.half_open_calls = 0
        self._lock = asyncio.Lock()

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        async with self._lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    log.info(f"Circuit '{self.name}' entering half-open state")
                else:
                    retry_after = self._time_until_reset()
                    raise CircuitBreakerOpen(self.name, retry_after)

            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.config.half_open_max_calls:
                    retry_after = self._time_until_reset()
                    raise CircuitBreakerOpen(self.name, retry_after)
                self.half_open_calls += 1

        # Execute the function
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self):
        """Handle successful call."""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.successes += 1
                if self.successes >= self.config.success_threshold:
                    self._reset()
                    log.info(f"Circuit '{self.name}' closed (recovered)")
            else:
                self.failures = max(0, self.failures - 1)

    async def _on_failure(self):
        """Handle failed call."""
        async with self._lock:
            self.failures += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                self._trip()
            elif self.failures >= self.config.failure_threshold:
                self._trip()

    def _trip(self):
        """Trip the circuit breaker to OPEN state."""
        self.state = CircuitState.OPEN
        self.successes = 0
        self.half_open_calls = 0
        log.warning(
            f"Circuit '{self.name}' opened after {self.failures} failures"
        )

    def _reset(self):
        """Reset circuit breaker to CLOSED state."""
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.successes = 0
        self.half_open_calls = 0
        self.last_failure_time = None

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try recovery."""
        if self.last_failure_time is None:
            return True
        return time.time() - self.last_failure_time >= self.config.recovery_timeout

    def _time_until_reset(self) -> float:
        """Calculate time until next reset attempt."""
        if self.last_failure_time is None:
            return 0.0
        elapsed = time.time() - self.last_failure_time
        return max(0.0, self.config.recovery_timeout - elapsed)

    def get_state(self) -> Dict:
        """Get current circuit breaker state."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failures": self.failures,
            "successes": self.successes,
            "last_failure": self.last_failure_time,
        }


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
    on_retry: Optional[Callable] = None,
):
    """
    Decorator for retry logic with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts
        base_delay: Initial delay between retries
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential calculation
        retryable_exceptions: Tuple of exceptions to retry on
        on_retry: Optional callback function called on retry
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_error = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_error = e
                    if attempt == max_attempts:
                        break

                    # Calculate delay with exponential backoff
                    delay = min(
                        base_delay * (exponential_base ** (attempt - 1)),
                        max_delay
                    )

                    log.warning(
                        f"Retry {attempt}/{max_attempts} for {func.__name__} "
                        f"after {delay:.1f}s: {e}"
                    )

                    if on_retry:
                        try:
                            on_retry(attempt, delay, e)
                        except Exception:
                            pass

                    await asyncio.sleep(delay)

            raise RetryExhausted(
                f"Function '{func.__name__}' failed",
                max_attempts,
                last_error
            )

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_error = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_error = e
                    if attempt == max_attempts:
                        break

                    delay = min(
                        base_delay * (exponential_base ** (attempt - 1)),
                        max_delay
                    )

                    log.warning(
                        f"Retry {attempt}/{max_attempts} for {func.__name__} "
                        f"after {delay:.1f}s: {e}"
                    )

                    if on_retry:
                        try:
                            on_retry(attempt, delay, e)
                        except Exception:
                            pass

                    time.sleep(delay)

            raise RetryExhausted(
                f"Function '{func.__name__}' failed",
                max_attempts,
                last_error
            )

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


@dataclass
class HealthStatus:
    """Health check status."""
    name: str
    status: str  # "healthy", "degraded", "unhealthy"
    message: str
    latency_ms: float
    last_check: str = field(default_factory=lambda: datetime.now().isoformat())
    details: Dict = field(default_factory=dict)


class ServiceHealth:
    """Service health check registry."""

    def __init__(self):
        self.checks: Dict[str, Callable] = {}
        self.results: Dict[str, HealthStatus] = {}
        self._lock = asyncio.Lock()

    def register(
        self,
        name: str,
        check_func: Callable,
    ):
        """Register a health check."""
        self.checks[name] = check_func

    async def check(self, name: str) -> HealthStatus:
        """Run a specific health check."""
        if name not in self.checks:
            return HealthStatus(
                name=name,
                status="unhealthy",
                message="Health check not registered",
                latency_ms=0.0
            )

        start = time.time()
        try:
            result = await self.checks[name]() if asyncio.iscoroutinefunction(
                self.checks[name]
            ) else self.checks[name]()

            latency_ms = (time.time() - start) * 1000

            if isinstance(result, tuple):
                status, message, details = result
            else:
                status, message = result, ""
                details = {}

            health = HealthStatus(
                name=name,
                status=status,
                message=message,
                latency_ms=latency_ms,
                details=details
            )
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            health = HealthStatus(
                name=name,
                status="unhealthy",
                message=f"Health check failed: {e}",
                latency_ms=latency_ms
            )

        async with self._lock:
            self.results[name] = health

        return health

    async def check_all(self) -> Dict[str, HealthStatus]:
        """Run all registered health checks."""
        results = {}
        for name in self.checks:
            results[name] = await self.check(name)
        return results

    def get_overall_status(self) -> str:
        """Get overall system health status."""
        if not self.results:
            return "unknown"

        statuses = [r.status for r in self.results.values()]

        if any(s == "unhealthy" for s in statuses):
            return "unhealthy"
        if any(s == "degraded" for s in statuses):
            return "degraded"
        return "healthy"

    def to_dict(self) -> Dict:
        """Export health status as dictionary."""
        return {
            "overall": self.get_overall_status(),
            "checks": {
                name: {
                    "status": status.status,
                    "message": status.message,
                    "latency_ms": round(status.latency_ms, 2),
                    "last_check": status.last_check,
                    "details": status.details,
                }
                for name, status in self.results.items()
            }
        }


# Global health checker instance
_health_checker: Optional[ServiceHealth] = None


def get_health_checker() -> ServiceHealth:
    """Get the global health checker instance."""
    global _health_checker
    if _health_checker is None:
        _health_checker = ServiceHealth()
    return _health_checker


# Convenience function for common retry scenarios
retry_network = functools.partial(
    retry_with_backoff,
    max_attempts=3,
    base_delay=1.0,
    retryable_exceptions=(ConnectionError, TimeoutError, OSError)
)

retry_cli = functools.partial(
    retry_with_backoff,
    max_attempts=2,
    base_delay=0.5,
    retryable_exceptions=(subprocess.CalledProcessError,)
)
