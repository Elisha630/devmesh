"""
Agent Manager Tests
-------------------
Tests for agent lifecycle and management.
"""

import pytest
from unittest.mock import MagicMock
from services.agent_manager import AgentManager
from models import AgentInfo, HardwareThrottle


class TestAgentRegistration:
    """Tests for agent registration."""

    def test_register_new_agent(self):
        """Register a new agent."""
        am = AgentManager()

        agent, is_reconnect, session_id = am.register_agent(
            model="claude-test",
            version="1.0",
            capabilities={"languages": ["python"]}
        )

        assert agent is not None
        assert agent.model == "claude-test"
        assert is_reconnect is False
        assert session_id is not None

    def test_first_agent_becomes_architect(self):
        """First registered agent becomes architect."""
        am = AgentManager()

        agent, _, _ = am.register_agent(model="first-agent")

        assert agent.role == "architect"
        assert am.architect == "first-agent"

    def test_subsequent_agents_are_regular(self):
        """Subsequent agents are regular agents."""
        am = AgentManager()

        am.register_agent(model="first-agent")
        agent2, _, _ = am.register_agent(model="second-agent")

        assert agent2.role == "agent"

    def test_get_agent(self):
        """Get agent by model name."""
        am = AgentManager()

        am.register_agent(model="test-agent", capabilities={"test": True})
        agent = am.get_agent("test-agent")

        assert agent is not None
        assert agent.model == "test-agent"

    def test_get_nonexistent_agent(self):
        """Get non-existent agent returns None."""
        am = AgentManager()

        agent = am.get_agent("nonexistent")

        assert agent is None


class TestAgentReconnection:
    """Tests for agent reconnection."""

    def test_reconnect_with_session_id(self):
        """Agent reconnects with same session ID."""
        am = AgentManager()
        storage_mock = MagicMock()
        storage_mock.get_agent.return_value = {"session_id": "session-123"}
        am.storage = storage_mock

        # First registration
        _, _, session_id = am.register_agent(
            model="test-agent",
            session_id="session-123"
        )

        # Simulate disconnect
        am.mark_disconnected("test-agent")

        # Reconnect with same session
        agent, is_reconnect, _ = am.register_agent(
            model="test-agent",
            session_id="session-123"
        )

        assert is_reconnect is True
        assert agent.status != "disconnected"

    def test_new_registration_different_session(self):
        """Different session ID is new registration."""
        am = AgentManager()

        am.register_agent(model="test-agent", session_id="session-1")

        # New registration with different session
        _, is_reconnect, _ = am.register_agent(
            model="test-agent",
            session_id="session-2"
        )

        assert is_reconnect is False


class TestAgentStatus:
    """Tests for agent status management."""

    def test_update_status(self):
        """Update agent status."""
        am = AgentManager()

        am.register_agent(model="test-agent")
        am.update_status("test-agent", "working", current_task="task-1")

        agent = am.get_agent("test-agent")
        assert agent.status == "working"
        assert agent.current_task == "task-1"

    def test_update_nonexistent_agent(self):
        """Update status of non-existent agent."""
        am = AgentManager()

        result = am.update_status("nonexistent", "working")
        assert result is False

    def test_is_agent_active(self):
        """Check if agent is active."""
        am = AgentManager()

        am.register_agent(model="test-agent")
        assert am.is_agent_active("test-agent") is True

        am.mark_disconnected("test-agent")
        assert am.is_agent_active("test-agent") is False

    def test_get_available_agents(self):
        """Get agents available for tasks."""
        am = AgentManager()

        am.register_agent(model="agent-1")
        am.register_agent(model="agent-2")
        am.update_status("agent-1", "working")

        available = am.get_available_agents()

        assert len(available) == 1
        assert available[0].model == "agent-2"


class TestAgentDisconnection:
    """Tests for agent disconnection handling."""

    def test_mark_disconnected(self):
        """Mark agent as disconnected."""
        am = AgentManager()

        am.register_agent(model="test-agent")
        result = am.mark_disconnected("test-agent")

        assert result is True
        assert am.get_agent("test-agent").status == "disconnected"
        assert am.is_in_grace_period("test-agent")

    def test_cancel_disconnect_grace(self):
        """Cancel disconnect grace period."""
        am = AgentManager()

        am.register_agent(model="test-agent")
        am.mark_disconnected("test-agent")

        result = am.cancel_disconnect_grace("test-agent")

        assert result is True
        assert not am.is_in_grace_period("test-agent")

    def test_get_expired_grace_periods(self):
        """Get agents whose grace periods expired."""
        am = AgentManager()
        am._disconnect_grace_sec = 0.01  # Very short for testing

        am.register_agent(model="agent-1")
        am.register_agent(model="agent-2")
        am.mark_disconnected("agent-1")
        am.mark_disconnected("agent-2")

        import time
        time.sleep(0.02)

        expired = am.get_expired_grace_periods()

        assert "agent-1" in expired
        assert "agent-2" in expired


class TestAgentRemoval:
    """Tests for agent removal."""

    def test_remove_agent(self):
        """Remove an agent."""
        am = AgentManager()

        am.register_agent(model="test-agent")
        result = am.remove_agent("test-agent")

        assert result is True
        assert am.get_agent("test-agent") is None

    def test_remove_architect_clears_architect(self):
        """Removing architect clears architect field."""
        am = AgentManager()

        am.register_agent(model="architect-agent")
        assert am.architect == "architect-agent"

        am.remove_agent("architect-agent")
        assert am.architect is None

    def test_remove_nonexistent(self):
        """Remove non-existent agent."""
        am = AgentManager()

        result = am.remove_agent("nonexistent")
        assert result is False


class TestAgentQueries:
    """Tests for agent query methods."""

    def test_get_agent_by_websocket_id(self):
        """Get agent by websocket ID."""
        am = AgentManager()

        agent, _, _ = am.register_agent(model="test-agent", websocket_id=42)

        found = am.get_agent_by_websocket_id(42)

        assert found is not None
        assert found.model == "test-agent"

    def test_get_roster(self):
        """Get agent roster."""
        am = AgentManager()

        am.register_agent(model="agent-1")
        am.register_agent(model="agent-2")

        roster = am.get_roster()

        assert roster["architect"] == "agent-1"
        assert len(roster["agents"]) == 2

    def test_get_agent_summary(self):
        """Get agent summary."""
        am = AgentManager()

        am.register_agent(model="test-agent")
        am.update_status("test-agent", "working", current_task="task-1")

        summary = am.get_agent_summary()

        assert len(summary) == 1
        assert summary[0]["model"] == "test-agent"
        assert summary[0]["status"] == "working"


class TestHardwareIntegration:
    """Tests for hardware integration."""

    def test_hardware_allocation_on_register(self):
        """Hardware allocated on registration."""
        am = AgentManager()
        hw = HardwareThrottle(max_vram=16, max_ram=32)
        am.hardware = hw

        am.register_agent(
            model="test-agent",
            resource_request={"vram_gb": 4, "ram_gb": 8}
        )

        assert hw.used_vram == 4.0
        assert hw.used_ram == 8.0

    def test_hardware_release_on_remove(self):
        """Hardware released on removal."""
        am = AgentManager()
        hw = HardwareThrottle(max_vram=16, max_ram=32)
        am.hardware = hw

        am.register_agent(
            model="test-agent",
            resource_request={"vram_gb": 4, "ram_gb": 8}
        )
        am.remove_agent("test-agent")

        assert hw.used_vram == 0.0
        assert hw.used_ram == 0.0

    def test_suspended_when_no_resources(self):
        """Agent suspended when no resources available."""
        am = AgentManager()
        hw = HardwareThrottle(max_vram=1, max_ram=1)
        am.hardware = hw

        agent, _, _ = am.register_agent(
            model="test-agent",
            resource_request={"vram_gb": 4, "ram_gb": 8}
        )

        assert agent.status == "suspended"


class TestAgentCallbacks:
    """Tests for agent event callbacks."""

    def test_registration_callback(self):
        """Callback called on registration."""
        am = AgentManager()
        registered_models = []

        def on_registered(model):
            registered_models.append(model)

        am.set_callbacks(on_registered=on_registered)
        am.register_agent(model="test-agent")

        assert len(registered_models) == 1
        assert registered_models[0] == "test-agent"

    def test_disconnection_callback(self):
        """Callback called on disconnection."""
        am = AgentManager()
        disconnected_models = []

        def on_disconnected(model):
            disconnected_models.append(model)

        am.set_callbacks(on_disconnected=on_disconnected)
        am.register_agent(model="test-agent")
        am.mark_disconnected("test-agent")

        assert len(disconnected_models) == 1
        assert disconnected_models[0] == "test-agent"


class TestAgentEdgeCases:
    """Edge case tests for agent manager."""

    def test_double_disconnect(self):
        """Marking disconnected twice."""
        am = AgentManager()

        am.register_agent(model="test-agent")
        am.mark_disconnected("test-agent")
        result = am.mark_disconnected("test-agent")

        # Second call should return False (already in grace period)
        assert result is False

    def test_update_heartbeat(self):
        """Update agent heartbeat."""
        am = AgentManager()

        am.register_agent(model="test-agent")
        old_last_seen = am.get_agent("test-agent").last_seen

        result = am.update_heartbeat("test-agent")

        assert result is True
        new_last_seen = am.get_agent("test-agent").last_seen
        assert new_last_seen != old_last_seen

    def test_set_agent_task(self):
        """Set agent task."""
        am = AgentManager()

        am.register_agent(model="test-agent")
        am.set_agent_task("test-agent", "task-1")

        agent = am.get_agent("test-agent")
        assert agent.current_task == "task-1"
        assert agent.status == "working"

    def test_clear_agent_task(self):
        """Clear agent task."""
        am = AgentManager()

        am.register_agent(model="test-agent")
        am.set_agent_task("test-agent", "task-1")
        am.set_agent_task("test-agent", None)

        agent = am.get_agent("test-agent")
        assert agent.current_task is None
        assert agent.status == "idle"
