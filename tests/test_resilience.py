"""
Resilience Module Tests
-----------------------
Tests for circuit breaker, retry logic, and health checks.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from resilience import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitBreakerConfig,
    retry_with_backoff,
    RetryExhausted,
    ServiceHealth,
    HealthStatus,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    @pytest.mark.asyncio
    async def test_circuit_initially_closed(self):
        """Circuit breaker starts in closed state."""
        cb = CircuitBreaker("test")
        assert cb.state.name == "CLOSED"
        assert cb.failures == 0

    @pytest.mark.asyncio
    async def test_successful_call(self):
        """Successful call passes through."""
        cb = CircuitBreaker("test")

        async def success_func():
            return "success"

        result = await cb.call(success_func)
        assert result == "success"
        assert cb.state.name == "CLOSED"

    @pytest.mark.asyncio
    async def test_circuit_opens_after_failures(self):
        """Circuit opens after threshold failures."""
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))

        async def fail_func():
            raise ValueError("Test error")

        # First 3 calls should raise ValueError
        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(fail_func)

        # Circuit should now be open
        assert cb.state.name == "OPEN"

        # Next call should raise CircuitBreakerOpen
        with pytest.raises(CircuitBreakerOpen):
            await cb.call(fail_func)

    @pytest.mark.asyncio
    async def test_circuit_half_open_recovery(self):
        """Circuit transitions to half-open then closed on recovery."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=0.1,  # Short timeout for testing
            success_threshold=1,
        )
        cb = CircuitBreaker("test", config)

        async def fail_func():
            raise ValueError("Test error")

        async def success_func():
            return "success"

        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail_func)

        assert cb.state.name == "OPEN"

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Next call should succeed (half-open -> closed)
        result = await cb.call(success_func)
        assert result == "success"
        assert cb.state.name == "CLOSED"

    @pytest.mark.asyncio
    async def test_circuit_get_state(self):
        """Circuit breaker state export."""
        cb = CircuitBreaker("test_service")
        state = cb.get_state()

        assert state["name"] == "test_service"
        assert state["state"] == "closed"
        assert state["failures"] == 0


class TestRetryWithBackoff:
    """Tests for retry decorator."""

    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        """Successful call should not retry."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.01)
        async def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await success_func()
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Should retry on failure."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.01)
        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"Attempt {call_count}")
            return "success"

        result = await fail_twice()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        """Should raise RetryExhausted after max attempts."""

        @retry_with_backoff(max_attempts=3, base_delay=0.01)
        async def always_fail():
            raise ValueError("Always fails")

        with pytest.raises(RetryExhausted) as exc_info:
            await always_fail()

        assert exc_info.value.attempts == 3
        assert "Always fails" in str(exc_info.value.last_error)

    @pytest.mark.asyncio
    async def test_retry_specific_exceptions(self):
        """Should only retry on specified exceptions."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.01, retryable_exceptions=(ValueError,))
        async def raise_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("Not retried")

        with pytest.raises(TypeError):
            await raise_type_error()

        assert call_count == 1  # Should not retry

    @pytest.mark.asyncio
    async def test_retry_with_callback(self):
        """Should call callback on retry."""
        callback_calls = []

        def on_retry(attempt, delay, error):
            callback_calls.append((attempt, delay, error))

        @retry_with_backoff(max_attempts=3, base_delay=0.1, on_retry=on_retry)
        async def fail_twice():
            if len(callback_calls) < 2:
                raise ValueError("Fail")
            return "success"

        await fail_twice()
        assert len(callback_calls) == 2

    def test_sync_function_retry(self):
        """Should work with sync functions too."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.01)
        def sync_fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"Attempt {call_count}")
            return "success"

        result = sync_fail_twice()
        assert result == "success"
        assert call_count == 3


class TestServiceHealth:
    """Tests for ServiceHealth class."""

    @pytest.mark.asyncio
    async def test_register_and_check(self):
        """Register and run a health check."""
        health = ServiceHealth()

        async def healthy_check():
            return "healthy", "All good", {"detail": "test"}

        health.register("test_service", healthy_check)
        result = await health.check("test_service")

        assert result.name == "test_service"
        assert result.status == "healthy"
        assert result.message == "All good"
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_check_unregistered(self):
        """Check returns error for unregistered service."""
        health = ServiceHealth()
        result = await health.check("unknown")

        assert result.status == "unhealthy"
        assert "not registered" in result.message

    @pytest.mark.asyncio
    async def test_check_all(self):
        """Run all registered health checks."""
        health = ServiceHealth()

        async def healthy_check():
            return "healthy", "OK", {}

        health.register("svc1", healthy_check)
        health.register("svc2", healthy_check)

        results = await health.check_all()

        assert len(results) == 2
        assert results["svc1"].status == "healthy"
        assert results["svc2"].status == "healthy"

    @pytest.mark.asyncio
    async def test_overall_status(self):
        """Calculate overall health status."""
        health = ServiceHealth()

        async def healthy():
            return "healthy", "OK", {}

        async def degraded():
            return "degraded", "Slow", {}

        async def unhealthy():
            return "unhealthy", "Down", {}

        # Initially unknown
        assert health.get_overall_status() == "unknown"

        # All healthy
        health.register("svc1", healthy)
        await health.check("svc1")
        assert health.get_overall_status() == "healthy"

        # Add degraded
        health.register("svc2", degraded)
        await health.check("svc2")
        assert health.get_overall_status() == "degraded"

        # Add unhealthy
        health.register("svc3", unhealthy)
        await health.check("svc3")
        assert health.get_overall_status() == "unhealthy"

    @pytest.mark.asyncio
    async def test_failed_check(self):
        """Handle exceptions in health checks."""
        health = ServiceHealth()

        async def broken_check():
            raise ValueError("Check failed")

        health.register("broken", broken_check)
        result = await health.check("broken")

        assert result.status == "unhealthy"
        assert "Check failed" in result.message

    @pytest.mark.asyncio
    async def test_export_to_dict(self):
        """Export health status as dictionary."""
        health = ServiceHealth()

        async def healthy_check():
            return "healthy", "OK", {"key": "value"}

        health.register("svc", healthy_check)
        await health.check("svc")

        data = health.to_dict()

        assert data["overall"] == "healthy"
        assert "svc" in data["checks"]
        assert data["checks"]["svc"]["status"] == "healthy"


class TestRetryScenarios:
    """Integration tests for retry patterns."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_with_retry(self):
        """Circuit breaker and retry work together."""
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=5))

        @retry_with_backoff(max_attempts=2, base_delay=0.01)
        async def flaky_operation():
            raise ValueError("Transient error")

        # First call should retry then fail
        with pytest.raises(RetryExhausted):
            await cb.call(flaky_operation)

        # Circuit still closed because retry absorbed failures
        assert cb.failures == 1

    @pytest.mark.asyncio
    async def test_exponential_backoff_timing(self):
        """Verify exponential backoff delays."""
        delays = []

        def record_delay(attempt, delay, error):
            delays.append(delay)

        @retry_with_backoff(
            max_attempts=4, base_delay=0.1, exponential_base=2.0, on_retry=record_delay
        )
        async def always_fail():
            raise ValueError("Fail")

        with pytest.raises(RetryExhausted):
            await always_fail()

        # Should have 3 delays (after attempts 1, 2, 3)
        assert len(delays) == 3
        # Delays should be approximately: 0.1, 0.2, 0.4
        assert delays[0] == pytest.approx(0.1, rel=0.1)
        assert delays[1] == pytest.approx(0.2, rel=0.1)
        assert delays[2] == pytest.approx(0.4, rel=0.1)
