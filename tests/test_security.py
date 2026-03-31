"""
Security Module Tests
---------------------
Tests for security.py validation and sanitization functions.
"""

import pytest
from pathlib import Path

# Import the security module
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from security import (
    sanitize_path,
    validate_task_input,
    sanitize_shell_input,
    is_safe_path,
    validate_model_name,
    validate_working_dir,
    SecurityError,
    ValidationError,
    PathTraversalError,
)


class TestSanitizePath:
    """Tests for path sanitization."""

    def test_valid_path(self, tmp_path):
        """Test sanitizing a valid path."""
        result = sanitize_path(str(tmp_path))
        assert isinstance(result, Path)
        assert result.exists()

    def test_path_traversal_detection(self, tmp_path):
        """Test detection of path traversal attempts."""
        base = tmp_path / "base"
        base.mkdir()

        with pytest.raises(PathTraversalError):
            sanitize_path("../../etc/passwd", base_dir=base)

    def test_null_bytes_blocked(self):
        """Test that null bytes are blocked."""
        with pytest.raises(PathTraversalError):
            sanitize_path("file\x00.txt")

    def test_path_too_long(self):
        """Test that excessively long paths are rejected."""
        with pytest.raises(ValidationError):
            sanitize_path("a" * 5000)

    def test_safe_relative_path(self, tmp_path):
        """Test that safe relative paths are allowed."""
        base = tmp_path / "base"
        base.mkdir()
        subdir = base / "subdir"
        subdir.mkdir()

        # Pass relative path within base directory
        result = sanitize_path("subdir", base_dir=base)
        # Result should be the absolute path
        assert result.resolve() == subdir.resolve()


class TestValidateTaskInput:
    """Tests for task input validation."""

    def test_valid_task(self):
        """Test valid task text passes."""
        result = validate_task_input("Create a Python function to calculate sum")
        assert result == "Create a Python function to calculate sum"

    def test_empty_task_rejected(self):
        """Test empty task text is rejected."""
        with pytest.raises(ValidationError):
            validate_task_input("")

    def test_non_string_rejected(self):
        """Test non-string input is rejected."""
        with pytest.raises(ValidationError):
            validate_task_input(123)

    def test_too_long_task_rejected(self):
        """Test excessively long task is rejected."""
        with pytest.raises(ValidationError):
            validate_task_input("x" * 20000)

    def test_control_chars_removed(self):
        """Test control characters are removed."""
        result = validate_task_input("Task\x01\x02text")
        assert "\x01" not in result
        assert "\x02" not in result


class TestSanitizeShellInput:
    """Tests for shell input sanitization."""

    def test_shell_quotes_added(self):
        """Test that shell quotes are added."""
        result = sanitize_shell_input("hello world")
        assert result == "'hello world'"

    def test_special_chars_escaped(self):
        """Test special characters are escaped."""
        result = sanitize_shell_input("hello; rm -rf /")
        assert ";" not in result or "'" in result

    def test_non_string_converted(self):
        """Test non-string values are converted."""
        result = sanitize_shell_input(123)
        # shlex.quote doesn't add quotes to safe strings like "123"
        assert "123" in result


class TestIsSafePath:
    """Tests for path safety checking."""

    def test_safe_path_allowed(self, tmp_path):
        """Test safe paths are allowed."""
        assert is_safe_path(str(tmp_path)) is True

    def test_traversal_path_blocked(self):
        """Test paths with traversal are blocked."""
        assert is_safe_path("../../../etc/passwd") is False

    def test_extension_check(self, tmp_path):
        """Test extension validation."""
        safe_file = tmp_path / "test.py"
        safe_file.touch()

        assert is_safe_path(str(safe_file), allowed_extensions={".py"}) is True
        assert is_safe_path(str(safe_file), allowed_extensions={".js"}) is False


class TestValidateModelName:
    """Tests for model name validation."""

    def test_valid_model_name(self):
        """Test valid model names pass."""
        assert validate_model_name("claude-sonnet") == "claude-sonnet"
        assert validate_model_name("gpt4") == "gpt4"
        assert validate_model_name("agent_123") == "agent_123"

    def test_empty_model_rejected(self):
        """Test empty model names are rejected."""
        with pytest.raises(ValidationError):
            validate_model_name("")

    def test_invalid_characters_rejected(self):
        """Test model names with invalid characters are rejected."""
        with pytest.raises(ValidationError):
            validate_model_name("model; rm -rf /")

    def test_too_long_rejected(self):
        """Test overly long model names are rejected."""
        with pytest.raises(ValidationError):
            validate_model_name("a" * 200)


class TestValidateWorkingDir:
    """Tests for working directory validation."""

    def test_valid_directory(self, tmp_path):
        """Test valid directory passes."""
        result = validate_working_dir(str(tmp_path))
        assert result == tmp_path

    def test_nonexistent_directory_rejected(self):
        """Test non-existent directory is rejected."""
        with pytest.raises(ValidationError):
            validate_working_dir("/nonexistent/path/12345")

    def test_file_not_directory_rejected(self, tmp_path):
        """Test that files are rejected (must be directory)."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("test")

        with pytest.raises(ValidationError):
            validate_working_dir(str(file_path))


class TestSecurityConfig:
    """Tests for security configuration."""

    def test_default_config_exists(self):
        """Test that default config is available."""
        from security import DEFAULT_SECURITY_CONFIG

        assert DEFAULT_SECURITY_CONFIG is not None
        assert DEFAULT_SECURITY_CONFIG.max_task_length > 0
        assert DEFAULT_SECURITY_CONFIG.max_path_length > 0
