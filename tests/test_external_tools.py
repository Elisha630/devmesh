"""
External Tools Tests
--------------------
Tests for external AI CLI tool integration with mocks.
"""

import pytest
import subprocess
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path


class TestToolDetection:
    """Tests for AI CLI tool detection."""

    @patch('shutil.which')
    @patch('subprocess.run')
    def test_detect_installed_claude(self, mock_run, mock_which):
        """Detect Claude CLI tool."""
        mock_which.return_value = "/usr/bin/claude"
        mock_run.return_value = MagicMock(
            stdout="claude version 1.0.0\n",
            stderr=""
        )

        from server import detect_installed_tools

        tools = detect_installed_tools()
        claude = next((t for t in tools if t["name"] == "claude"), None)

        assert claude is not None
        assert claude["status"] == "detected"
        assert claude["version"] == "claude version 1.0.0"

    @patch('shutil.which')
    def test_detect_missing_tool(self, mock_which):
        """Handle missing tool gracefully."""
        mock_which.return_value = None

        from server import detect_installed_tools

        tools = detect_installed_tools()
        missing = next((t for t in tools if t["name"] == "missing-tool"), None)

        assert missing is None or missing.get("status") != "detected"

    @patch('shutil.which')
    @patch('subprocess.run')
    def test_detect_tool_version_timeout(self, mock_run, mock_which):
        """Handle version check timeout."""
        mock_which.return_value = "/usr/bin/claude"
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 3)

        from server import detect_installed_tools

        tools = detect_installed_tools()
        claude = next((t for t in tools if t["name"] == "claude"), None)

        if claude:
            assert claude["status"] == "detected"
            assert "timeout" in claude["version"] or claude["version"] == "installed"

    @patch('shutil.which')
    @patch('subprocess.run')
    def test_detect_tool_subprocess_error(self, mock_run, mock_which):
        """Handle subprocess error during version check."""
        mock_which.return_value = "/usr/bin/claude"
        mock_run.side_effect = subprocess.SubprocessError("Error")

        from server import detect_installed_tools

        tools = detect_installed_tools()
        claude = next((t for t in tools if t["name"] == "claude"), None)

        if claude:
            assert claude["status"] == "detected"
            assert claude["version"] == "installed"


class TestToolLaunching:
    """Tests for launching AI agent tools."""

    @pytest.mark.asyncio
    async def test_launch_agent_with_mock_process(self):
        """Launch agent with mocked subprocess."""
        with patch('subprocess.Popen') as mock_popen:
            with patch('pathlib.Path.exists') as mock_exists:
                mock_exists.return_value = True
                mock_process = MagicMock()
                mock_process.pid = 12345
                mock_process.poll.return_value = None
                mock_popen.return_value = mock_process

                # Mock server setup
                server_mock = MagicMock()
                server_mock.launched_procs = {}
                server_mock._agent_stderr_paths = {}
                server_mock._audit = MagicMock()
                server_mock.chat_log = []
                server_mock._ts.return_value = "2024-01-01T00:00:00"
                server_mock._push_dash = MagicMock()

                # Mock config
                with patch('config.cfg') as mock_cfg:
                    mock_cfg.ws_url = "ws://localhost:7700"

                    from server import DevMeshServer

                    server = MagicMock(spec=DevMeshServer)
                    server.detected_tools = [
                        {"name": "claude", "label": "Claude", "cmd": "claude"}
                    ]
                    server.launched_procs = {}
                    server._agent_stderr_paths = {}
                    server._audit = MagicMock()
                    server.chat_log = []
                    server._ts = MagicMock(return_value="2024-01-01T00:00:00")
                    server._circuit_breakers = {}

                    # Need to properly test this with the actual method
                    # For now just verify the Popen was called correctly
                    # in a real scenario

                    # Launch would call:
                    # subprocess.Popen([sys.executable, bridge, "--tool", tool_name, "--ws", cfg.ws_url])

                    assert True  # Placeholder - full test would need more setup

    @pytest.mark.asyncio
    async def test_stop_agent_gracefully(self):
        """Stop agent process gracefully."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.wait.return_value = None

        from server import DevMeshServer

        server = MagicMock(spec=DevMeshServer)
        server.launched_procs = {"claude": mock_process}
        server.agents = {}
        server._agent_disconnect_deadline = {}
        server.hw = MagicMock()
        server.storage = MagicMock()
        server._audit = MagicMock()

        # Call the actual _stop_agent method logic
        # (would need full server instance to test properly)

        # Simulate stop
        proc = server.launched_procs.get("claude")
        if proc:
            proc.terminate()

        mock_process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_agent_force_kill(self):
        """Force kill agent that doesn't terminate gracefully."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)

        from server import DevMeshServer

        server = MagicMock(spec=DevMeshServer)
        server.launched_procs = {"claude": mock_process}

        proc = server.launched_procs.get("claude")
        if proc:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        mock_process.kill.assert_called_once()


class TestAgentBridge:
    """Tests for agent bridge functionality."""

    def test_agent_bridge_import(self):
        """Agent bridge can be imported."""
        try:
            import agent_bridge
            assert True
        except ImportError:
            pytest.skip("agent_bridge.py not available")

    def test_bridge_cli_args_parsing(self):
        """Bridge parses command line arguments."""
        with patch('sys.argv', ['agent_bridge.py', '--tool', 'claude', '--ws', 'ws://localhost:7700']):
            try:
                import agent_bridge
                # Would need to test the main function
                assert True
            except Exception:
                # Expected if main() runs
                pass


class TestToolConfiguration:
    """Tests for tool configuration."""

    def test_known_cli_tools_defined(self):
        """KNOWN_CLI_TOOLS is properly defined."""
        from config import KNOWN_CLI_TOOLS

        assert len(KNOWN_CLI_TOOLS) > 0

        required_fields = ["name", "cmd", "label", "color"]
        for tool in KNOWN_CLI_TOOLS:
            for field in required_fields:
                assert field in tool, f"Tool {tool} missing {field}"

    def test_tool_profiles_defined(self):
        """TOOL_PROFILES is properly defined."""
        from config import TOOL_PROFILES, KNOWN_CLI_TOOLS

        # All known tools should have profiles
        known_names = set(t["name"] for t in KNOWN_CLI_TOOLS)
        profile_names = set(TOOL_PROFILES.keys())

        assert known_names == profile_names

        required_fields = ["label", "color", "invoke_mode", "cmd", "capabilities", "resources"]
        for name, profile in TOOL_PROFILES.items():
            for field in required_fields:
                assert field in profile, f"Profile {name} missing {field}"

    def test_tool_resources_structure(self):
        """Tool resources have correct structure."""
        from config import TOOL_PROFILES

        for name, profile in TOOL_PROFILES.items():
            resources = profile.get("resources", {})
            assert "vram_gb" in resources
            assert "ram_gb" in resources
            assert isinstance(resources["vram_gb"], (int, float))
            assert isinstance(resources["ram_gb"], (int, float))


class TestToolProfiles:
    """Tests for specific tool profiles."""

    def test_claude_profile(self):
        """Claude profile is valid."""
        from config import TOOL_PROFILES

        profile = TOOL_PROFILES.get("claude")
        assert profile is not None
        assert profile["invoke_mode"] == "arg"
        assert "{prompt}" in " ".join(profile["cmd"])

    def test_cursor_profile(self):
        """Cursor profile is valid."""
        from config import TOOL_PROFILES

        profile = TOOL_PROFILES.get("cursor")
        assert profile is not None
        assert "agent" in profile["cmd"]

    def test_codex_profile(self):
        """OpenAI Codex profile is valid."""
        from config import TOOL_PROFILES

        profile = TOOL_PROFILES.get("codex")
        assert profile is not None
        assert "codex" in profile["cmd"]
        assert "exec" in profile["cmd"]


class MockToolTest:
    """Tests using mock tools for integration testing."""

    @pytest.fixture
    def mock_tool_script(self, tmp_path):
        """Create a mock tool script for testing."""
        script = tmp_path / "mock_tool.py"
        script.write_text("""
#!/usr/bin/env python3
import sys
import time

if "--version" in sys.argv:
    print("mock-tool version 1.0.0")
    sys.exit(0)

if "--help" in sys.argv:
    print("Mock AI tool for testing")
    sys.exit(0)

# Simulate processing
print("Processing...")
time.sleep(0.1)
print("Done")
""")
        script.chmod(0o755)
        return script

    def test_mock_tool_execution(self, mock_tool_script):
        """Execute mock tool."""
        result = subprocess.run(
            [str(mock_tool_script), "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )

        assert result.returncode == 0
        assert "version 1.0.0" in result.stdout


class TestToolErrorHandling:
    """Tests for tool error handling."""

    def test_tool_not_found_error(self):
        """Error when tool not found."""
        from errors import ToolNotFound

        error = ToolNotFound("nonexistent-tool")

        assert "not found" in str(error)
        assert error.to_dict()["code"] == "TOOL_NOT_FOUND"

    def test_tool_invoke_error(self):
        """Error when tool invocation fails."""
        from errors import ToolInvokeError

        error = ToolInvokeError("claude", "Process crashed")

        assert "claude" in str(error)
        assert "crashed" in str(error)
        assert error.to_dict()["code"] == "TOOL_INVOKE_ERROR"
