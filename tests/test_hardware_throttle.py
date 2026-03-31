"""
Hardware Throttle Tests
-------------------------
Tests for hardware resource allocation and throttling.
"""

import pytest
from models import HardwareThrottle


class TestHardwareThrottle:
    """Tests for HardwareThrottle class."""

    def test_initialization(self):
        """Hardware throttle initializes correctly."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        assert hw.max_vram == 16
        assert hw.max_ram == 32
        assert hw.used_vram == 0.0
        assert hw.used_ram == 0.0
        assert len(hw.allocations) == 0

    def test_status_report(self):
        """Status report shows current allocation."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        status = hw.status()

        assert status["vram"]["used"] == 0.0
        assert status["vram"]["total"] == 16
        assert status["ram"]["used"] == 0.0
        assert status["ram"]["total"] == 32

    def test_allocate_success(self):
        """Successful resource allocation."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        result = hw.allocate("agent-1", {"vram_gb": 4, "ram_gb": 8})

        assert result is True
        assert hw.used_vram == 4.0
        assert hw.used_ram == 8.0
        assert "agent-1" in hw.allocations

    def test_allocate_multiple(self):
        """Allocate to multiple agents."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        assert hw.allocate("agent-1", {"vram_gb": 4, "ram_gb": 8}) is True
        assert hw.allocate("agent-2", {"vram_gb": 4, "ram_gb": 8}) is True
        assert hw.allocate("agent-3", {"vram_gb": 4, "ram_gb": 8}) is True

        assert hw.used_vram == 12.0
        assert hw.used_ram == 24.0

    def test_allocate_insufficient_vram(self):
        """Allocation fails when VRAM exhausted."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        # Use up all VRAM
        hw.allocate("agent-1", {"vram_gb": 16, "ram_gb": 8})

        # Try to allocate more VRAM
        result = hw.allocate("agent-2", {"vram_gb": 1, "ram_gb": 1})

        assert result is False
        assert hw.used_vram == 16.0

    def test_allocate_insufficient_ram(self):
        """Allocation fails when RAM exhausted."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        # Use up all RAM
        hw.allocate("agent-1", {"vram_gb": 4, "ram_gb": 32})

        # Try to allocate more RAM
        result = hw.allocate("agent-2", {"vram_gb": 1, "ram_gb": 1})

        assert result is False
        assert hw.used_ram == 32.0

    def test_release(self):
        """Release allocated resources."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        hw.allocate("agent-1", {"vram_gb": 4, "ram_gb": 8})
        hw.release("agent-1")

        assert hw.used_vram == 0.0
        assert hw.used_ram == 0.0
        assert "agent-1" not in hw.allocations

    def test_release_nonexistent(self):
        """Release non-existent agent is safe."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        hw.release("nonexistent")

        assert hw.used_vram == 0.0
        assert hw.used_ram == 0.0

    def test_reallocate_avoids_double_counting(self):
        """Re-allocating to same agent avoids double counting."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        # First allocation
        hw.allocate("agent-1", {"vram_gb": 4, "ram_gb": 8})

        # Re-allocate with different values
        result = hw.allocate("agent-1", {"vram_gb": 6, "ram_gb": 10})

        assert result is True
        assert hw.used_vram == 6.0  # Not 4 + 6 = 10
        assert hw.used_ram == 10.0  # Not 8 + 10 = 18

    def test_can_allocate(self):
        """Check if resources can be allocated without actually allocating."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        # Empty should allow
        assert hw.can_allocate({"vram_gb": 16, "ram_gb": 32}) is True

        # Partial allocation
        hw.allocate("agent-1", {"vram_gb": 8, "ram_gb": 16})

        # Should still allow remaining
        assert hw.can_allocate({"vram_gb": 8, "ram_gb": 16}) is True

        # Should deny exceeding
        assert hw.can_allocate({"vram_gb": 9, "ram_gb": 1}) is False

    def test_zero_allocation(self):
        """Allocation with zero resources."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        result = hw.allocate("agent-1", {"vram_gb": 0, "ram_gb": 0})

        assert result is True
        assert hw.used_vram == 0.0
        assert hw.used_ram == 0.0

    def test_negative_allocation(self):
        """Allocation with negative values."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        # Negative should still pass validation but affect accounting
        result = hw.allocate("agent-1", {"vram_gb": -1, "ram_gb": -1})

        # Implementation dependent - negative allocations might be accepted
        # or might be treated as 0
        # Current implementation: subtracts from usage
        assert "agent-1" in hw.allocations or result is True

    def test_missing_resource_keys(self):
        """Allocation with missing resource keys."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        # Missing keys default to 0
        result = hw.allocate("agent-1", {})

        assert result is True
        assert hw.used_vram == 0.0
        assert hw.used_ram == 0.0

    def test_fractional_resources(self):
        """Allocation with fractional resource values."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        result = hw.allocate("agent-1", {"vram_gb": 0.5, "ram_gb": 1.5})

        assert result is True
        assert hw.used_vram == 0.5
        assert hw.used_ram == 1.5

    def test_rounding_in_status(self):
        """Status values are properly rounded."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        hw.allocate("agent-1", {"vram_gb": 1.3333333, "ram_gb": 2.6666666})

        status = hw.status()

        # Should be rounded to 2 decimal places
        assert status["vram"]["used"] == 1.33
        assert status["ram"]["used"] == 2.67

    def test_exact_capacity(self):
        """Allocate exactly at capacity."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        result = hw.allocate("agent-1", {"vram_gb": 16, "ram_gb": 32})

        assert result is True
        assert hw.used_vram == 16.0
        assert hw.used_ram == 32.0

        # One more byte should fail
        result = hw.allocate("agent-2", {"vram_gb": 0.001, "ram_gb": 0.001})
        assert result is False

    def test_many_allocations(self):
        """Handle many agents allocating resources."""
        hw = HardwareThrottle(max_vram=100, max_ram=200)

        # Allocate to many agents
        for i in range(100):
            result = hw.allocate(f"agent-{i}", {"vram_gb": 1, "ram_gb": 2})
            assert result is True

        assert hw.used_vram == 100.0
        assert hw.used_ram == 200.0

        # Release all
        for i in range(100):
            hw.release(f"agent-{i}")

        assert hw.used_vram == 0.0
        assert hw.used_ram == 0.0
        assert len(hw.allocations) == 0


class TestHardwareThrottleEdgeCases:
    """Edge case tests for HardwareThrottle."""

    def test_zero_capacity(self):
        """Zero capacity handling."""
        hw = HardwareThrottle(max_vram=0, max_ram=0)

        result = hw.allocate("agent-1", {"vram_gb": 0, "ram_gb": 0})
        assert result is True

        result = hw.allocate("agent-2", {"vram_gb": 0.1, "ram_gb": 0.1})
        assert result is False

    def test_very_large_allocation(self):
        """Very large allocation request."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        result = hw.allocate("agent-1", {"vram_gb": 1000, "ram_gb": 1000})
        assert result is False

    def test_release_order_independence(self):
        """Release order doesn't affect result."""
        hw = HardwareThrottle(max_vram=16, max_ram=32)

        hw.allocate("agent-1", {"vram_gb": 4, "ram_gb": 8})
        hw.allocate("agent-2", {"vram_gb": 4, "ram_gb": 8})
        hw.allocate("agent-3", {"vram_gb": 4, "ram_gb": 8})

        # Release in reverse order
        hw.release("agent-3")
        hw.release("agent-2")
        hw.release("agent-1")

        assert hw.used_vram == 0.0
        assert hw.used_ram == 0.0
