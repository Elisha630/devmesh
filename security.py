"""
DevMesh Security Module
-----------------------
Input validation, sanitization, and security utilities.
"""

__all__ = [
    "sanitize_path",
    "validate_task_input",
    "sanitize_shell_input",
    "is_safe_path",
    "validate_model_name",
    "validate_working_dir",
    "SecurityError",
    "ValidationError",
    "PathTraversalError",
]

import re
import shlex
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


class SecurityError(Exception):
    """Base security exception."""
    pass


class ValidationError(SecurityError):
    """Input validation failed."""
    pass


class PathTraversalError(SecurityError):
    """Path traversal attempt detected."""
    pass


# Maximum lengths to prevent DoS
MAX_TASK_LENGTH = 10000
MAX_MODEL_NAME_LENGTH = 100
MAX_PATH_LENGTH = 4096
MAX_FILE_CONTENT_SIZE = 50 * 1024 * 1024  # 50MB

# Forbidden characters in shell contexts
SHELL_FORBIDDEN_CHARS = re.compile(r'[;|&$`\\]')
SHELL_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# Allowed model name pattern
MODEL_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

# Path traversal patterns
PATH_TRAVERSAL_PATTERNS = [
    re.compile(r'\.\.[/\\]'),  # ../ or ..\
    re.compile(r'[/\\]\.\.'),  # /.. or \..
    re.compile(r'^\.\.'),  # Starts with ..
    re.compile(r'\.{2,}'),  # Three or more dots
]


def sanitize_path(path: str | Path, base_dir: Optional[Path] = None) -> Path:
    """
    Sanitize a file path to prevent path traversal attacks.

    Args:
        path: The path to sanitize
        base_dir: Optional base directory to resolve against

    Returns:
        Resolved Path object

    Raises:
        PathTraversalError: If path traversal is detected
    """
    if path is None:
        raise ValidationError("Path cannot be None")

    path_str = str(path)

    # Check length
    if len(path_str) > MAX_PATH_LENGTH:
        raise ValidationError(f"Path exceeds maximum length of {MAX_PATH_LENGTH}")

    # Check for null bytes
    if '\x00' in path_str:
        raise PathTraversalError("Path contains null bytes")

    # Check for path traversal patterns
    for pattern in PATH_TRAVERSAL_PATTERNS:
        if pattern.search(path_str):
            raise PathTraversalError(f"Path traversal detected in: {path_str[:50]}")

    # If base_dir specified, join and resolve within that directory
    if base_dir:
        base = base_dir.expanduser().resolve()
        # Join the path with base, then resolve
        resolved = (base / path_str).expanduser().resolve()
        # Ensure the resolved path is still within base
        try:
            resolved.relative_to(base)
        except ValueError:
            raise PathTraversalError(
                f"Path {resolved} is outside allowed base directory {base}"
            )
    else:
        resolved = Path(path_str).expanduser().resolve()

    return resolved


def validate_task_input(task_text: str) -> str:
    """
    Validate and sanitize task input text.

    Args:
        task_text: The task description/instruction

    Returns:
        Sanitized task text

    Raises:
        ValidationError: If input is invalid
    """
    if not task_text:
        raise ValidationError("Task text cannot be empty")

    if not isinstance(task_text, str):
        raise ValidationError("Task text must be a string")

    # Check length
    if len(task_text) > MAX_TASK_LENGTH:
        raise ValidationError(
            f"Task text exceeds maximum length of {MAX_TASK_LENGTH} characters"
        )

    # Remove control characters
    sanitized = SHELL_CONTROL_CHARS.sub('', task_text)

    # Check for suspicious patterns (but don't block - just warn via logging)
    suspicious = [
        r'rm\s+-rf',
        r':\s*\{\s*:\s*\}',  # Bash fork bomb
        r'\$\(.*?\)',  # Command substitution
        r'`.*?`',  # Backtick command substitution
    ]

    return sanitized


def sanitize_shell_input(value: str) -> str:
    """
    Sanitize input that will be passed to shell commands.
    Uses shlex.quote for safety.

    Args:
        value: The value to sanitize

    Returns:
        Shell-safe quoted string
    """
    if not isinstance(value, str):
        value = str(value)

    # Remove control characters
    value = SHELL_CONTROL_CHARS.sub('', value)

    # Use shlex.quote to escape for shell
    return shlex.quote(value)


def is_safe_path(path: str | Path, allowed_extensions: Optional[set] = None) -> bool:
    """
    Check if a path is safe to use.

    Args:
        path: The path to check
        allowed_extensions: Optional set of allowed file extensions

    Returns:
        True if path is safe, False otherwise
    """
    try:
        sanitized = sanitize_path(path)
    except SecurityError:
        return False

    if allowed_extensions:
        ext = sanitized.suffix.lower()
        if ext not in allowed_extensions:
            return False

    return True


def validate_model_name(model: str) -> str:
    """
    Validate agent model name.

    Args:
        model: The model identifier

    Returns:
        Validated model name

    Raises:
        ValidationError: If model name is invalid
    """
    if not model:
        raise ValidationError("Model name cannot be empty")

    if not isinstance(model, str):
        raise ValidationError("Model name must be a string")

    if len(model) > MAX_MODEL_NAME_LENGTH:
        raise ValidationError(
            f"Model name exceeds maximum length of {MAX_MODEL_NAME_LENGTH}"
        )

    if not MODEL_NAME_PATTERN.match(model):
        raise ValidationError(
            "Model name can only contain alphanumeric characters, underscores, and hyphens"
        )

    return model


def validate_working_dir(working_dir: str) -> Path:
    """
    Validate and sanitize working directory.

    Args:
        working_dir: The working directory path

    Returns:
        Validated Path object

    Raises:
        ValidationError: If working directory is invalid
    """
    if not working_dir:
        raise ValidationError("Working directory cannot be empty")

    path = sanitize_path(working_dir)

    if not path.exists():
        raise ValidationError(f"Working directory does not exist: {path}")

    if not path.is_dir():
        raise ValidationError(f"Path is not a directory: {path}")

    # Check if writable (basic check)
    try:
        test_file = path / ".devmesh_write_test"
        test_file.touch()
        test_file.unlink()
    except OSError as e:
        raise ValidationError(f"Working directory is not writable: {e}")

    return path


@dataclass(frozen=True)
class SecurityConfig:
    """Security configuration settings."""
    max_task_length: int = MAX_TASK_LENGTH
    max_model_name_length: int = MAX_MODEL_NAME_LENGTH
    max_path_length: int = MAX_PATH_LENGTH
    max_file_content_size: int = MAX_FILE_CONTENT_SIZE
    allowed_extensions: frozenset = frozenset([
        '.py', '.js', '.ts', '.jsx', '.tsx', '.json', '.yaml', '.yml',
        '.md', '.txt', '.toml', '.ini', '.cfg', '.rs', '.go', '.java',
        '.kt', '.swift', '.c', '.cpp', '.h', '.hpp', '.rb', '.php',
    ])
    forbidden_commands: frozenset = frozenset([
        'rm -rf /',
        'rm -rf /*',
        ':(){ :|:& };:',  # Fork bomb
        'dd if=/dev/zero',
        'mkfs',
        'fdisk',
    ])


# Default security config
DEFAULT_SECURITY_CONFIG = SecurityConfig()
