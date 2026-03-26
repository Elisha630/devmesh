"""
DevMesh Configuration Management
---------------------------------
Centralized configuration for DevMesh server and agents.
Supports environment variables and config files.
"""

__all__ = [
    "ServerConfig",
    "AgentConfig",
    "KNOWN_CLI_TOOLS",
    "TOOL_PROFILES",
    "get_server_config",
    "get_agent_config",
]

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional

# ── Server Configuration ────────────────────────────────────────────────────

def _get_ws_host():
    return os.getenv("DEVMESH_WS_HOST", "127.0.0.1")

def _get_ws_port():
    return int(os.getenv("DEVMESH_WS_PORT", "7700"))

def _get_dashboard_port():
    return int(os.getenv("DEVMESH_DASHBOARD_PORT", "7702"))

def _get_http_port():
    return int(os.getenv("DEVMESH_HTTP_PORT", "7701"))

@dataclass
class ServerConfig:
    """Server runtime configuration."""
    ws_host: str = field(default_factory=_get_ws_host)
    ws_port: int = field(default_factory=_get_ws_port)
    dashboard_port: int = field(default_factory=_get_dashboard_port)
    http_port: int = field(default_factory=_get_http_port)
    
    # Timeouts and thresholds
    lock_ttl_sec: int = int(os.getenv("DEVMESH_LOCK_TTL_SEC", "15"))
    heartbeat_grace_sec: int = int(os.getenv("DEVMESH_HEARTBEAT_GRACE_SEC", "5"))
    # If an agent disconnects, keep its locks/tasks for this long.
    # If it reconnects before this deadline, tasks can resume.
    agent_reconnect_grace_sec: int = int(os.getenv("DEVMESH_AGENT_RECONNECT_GRACE_SEC", "30"))
    heartbeat_interval_sec: int = int(os.getenv("DEVMESH_HEARTBEAT_INTERVAL_SEC", "4"))
    ai_cli_version_timeout_sec: int = int(os.getenv("DEVMESH_CLI_VERSION_TIMEOUT_SEC", "3"))
    ai_cli_invoke_timeout_sec: int = int(os.getenv("DEVMESH_CLI_INVOKE_TIMEOUT_SEC", "120"))
    
    # Storage
    audit_log_dir: Path = Path(os.getenv("DEVMESH_AUDIT_DIR", ".devmesh"))
    audit_log_file: str = "audit.jsonl"
    
    # Hardware limits
    gpu_vram_gb: float = float(os.getenv("DEVMESH_GPU_VRAM_GB", "16"))
    ram_gb: float = float(os.getenv("DEVMESH_RAM_GB", "32"))
    
    # Dashboard
    auto_open_browser: bool = os.getenv("DEVMESH_AUTO_OPEN_BROWSER", "true").lower() in ("true", "1", "yes")

    # UI history sampling
    hardware_sample_interval_sec: float = float(os.getenv("DEVMESH_HARDWARE_SAMPLE_INTERVAL_SEC", "2"))
    hardware_history_len: int = int(os.getenv("DEVMESH_HARDWARE_HISTORY_LEN", "120"))

    # Conflict resolution rate limiting
    conflict_resolve_cooldown_sec: int = int(os.getenv("DEVMESH_CONFLICT_RESOLVE_COOLDOWN_SEC", "15"))
    
    # Logging
    log_level: str = os.getenv("DEVMESH_LOG_LEVEL", "INFO")
    log_file: Optional[str] = os.getenv("DEVMESH_LOG_FILE", None)
    
    def __post_init__(self):
        """Validate and initialize configuration."""
        self.audit_log_dir.mkdir(parents=True, exist_ok=True)
        if not (1 <= self.ws_port <= 65535):
            raise ValueError(f"Invalid ws_port: {self.ws_port}")
        if not (1 <= self.http_port <= 65535):
            raise ValueError(f"Invalid http_port: {self.http_port}")
        if not (1 <= self.dashboard_port <= 65535):
            raise ValueError(f"Invalid dashboard_port: {self.dashboard_port}")
    
    @property
    def audit_log_path(self) -> Path:
        return self.audit_log_dir / self.audit_log_file
    
    @property
    def ws_url(self) -> str:
        return f"ws://{self.ws_host}:{self.ws_port}"
    
    @property
    def dashboard_ws_url(self) -> str:
        return f"ws://{self.ws_host}:{self.dashboard_port}"
    
    @property
    def http_url(self) -> str:
        return f"http://{self.ws_host}:{self.http_port}"


@dataclass
class AgentConfig:
    """Agent bridge configuration."""
    ws_url: str = os.getenv("DEVMESH_SERVER_URL", "ws://127.0.0.1:7700")
    tool_name: Optional[str] = None
    heartbeat_interval_sec: int = int(os.getenv("DEVMESH_AGENT_HEARTBEAT_SEC", "4"))
    cli_invoke_timeout_sec: int = int(os.getenv("DEVMESH_AGENT_CLI_TIMEOUT_SEC", "240"))
    ping_interval_sec: int = int(os.getenv("DEVMESH_AGENT_PING_INTERVAL_SEC", "20"))
    log_level: str = os.getenv("DEVMESH_LOG_LEVEL", "INFO")


# ── Known AI CLI Tools ──────────────────────────────────────────────────────
# Shared tool definitions

KNOWN_CLI_TOOLS: list[Dict] = [
    {"name": "claude",   "cmd": "claude",   "label": "Claude Code",      "color": "#D4A847"},
    {"name": "gemini",   "cmd": "gemini",   "label": "Gemini CLI",       "color": "#4285F4"},
    {"name": "codex",    "cmd": "codex",    "label": "OpenAI Codex",     "color": "#10A37F"},
    {"name": "aider",    "cmd": "aider",    "label": "Aider",            "color": "#7C3AED"},
    {"name": "continue", "cmd": "continue", "label": "Continue",         "color": "#06B6D4"},
    {"name": "cody",     "cmd": "cody",     "label": "Sourcegraph Cody", "color": "#FF5543"},
    {"name": "cursor",   "cmd": "cursor",   "label": "Cursor",           "color": "#0EA5E9"},
    {"name": "ollama",   "cmd": "ollama",   "label": "Ollama",           "color": "#F97316"},
    {"name": "sgpt",     "cmd": "sgpt",     "label": "ShellGPT",         "color": "#8B5CF6"},
    {"name": "gh",       "cmd": "gh",       "label": "GitHub Copilot",   "color": "#238636"},
]

TOOL_PROFILES: Dict = {
    "claude": {
        "label": "Claude Code",
        "color": "#D4A847",
        "invoke_mode": "arg",
        "cmd": ["claude", "--print", "{prompt}"],
        "capabilities": {"languages": ["python","javascript","typescript","go","rust","java"],
                         "frameworks": ["react","django","fastapi","express","nextjs"]},
        "resources": {"vram_gb": 0, "ram_gb": 2},
    },
    "gemini": {
        "label": "Gemini CLI",
        "color": "#4285F4",
        "invoke_mode": "arg",
        # ✅ FIX 5.6: Use a known-stable Gemini model as default
        # Availability varies by account/project/quota. Override with DEVMESH_GEMINI_MODEL env var.
        "cmd": [
            "gemini",
            "--model", "gemini-2.0-flash",
            "--approval-mode", "yolo",
            "--prompt", "{prompt}",
            "--output-format", "text",
        ],
        "capabilities": {"languages": ["python","javascript","go","java","kotlin"],
                         "frameworks": ["flutter","firebase","spring"]},
        "resources": {"vram_gb": 0, "ram_gb": 2},
    },
    "codex": {
        "label": "OpenAI Codex",
        "color": "#10A37F",
        "invoke_mode": "arg",
        # Codex defaults to an interactive TUI if no subcommand is provided.
        # Use `exec --json` for robust headless invocation.
        "cmd": [
            "codex",
            "--ask-for-approval", "never",
            "--sandbox", "workspace-write",
            "exec",
            "--skip-git-repo-check",
            "--color", "never",
            "--json",
            "--cd", "{working_dir}",
            "{prompt}",
        ],
        "capabilities": {"languages": ["python","javascript","typescript","c","cpp"],
                         "frameworks": ["react","vue","express"]},
        "resources": {"vram_gb": 0, "ram_gb": 2},
    },
    "aider": {
        "label": "Aider",
        "color": "#7C3AED",
        "invoke_mode": "stdin",
        "cmd": ["aider", "--no-git", "--yes"],
        "capabilities": {"languages": ["python","javascript","typescript","rust","go"],
                         "specializations": ["refactoring","debugging"]},
        "resources": {"vram_gb": 0, "ram_gb": 3},
    },
    "continue": {
        "label": "Continue",
        "color": "#06B6D4",
        "invoke_mode": "arg",
        "cmd": ["continue", "dev"],
        "capabilities": {"languages": ["python","javascript","typescript","rust","go"],
                         "specializations": ["autocomplete","refactoring"]},
        "resources": {"vram_gb": 0, "ram_gb": 2},
    },
    "ollama": {
        "label": "Ollama",
        "color": "#F97316",
        "invoke_mode": "arg",
        "cmd": ["ollama", "run", "llama3", "{prompt}"],
        "capabilities": {"languages": ["python","javascript","bash"],
                         "specializations": ["local","offline"]},
        "resources": {"vram_gb": 8, "ram_gb": 8},
    },
    "sgpt": {
        "label": "ShellGPT",
        "color": "#8B5CF6",
        "invoke_mode": "arg",
        "cmd": ["sgpt", "{prompt}"],
        "capabilities": {"languages": ["python","bash","powershell"],
                         "specializations": ["shell","scripting"]},
        "resources": {"vram_gb": 0, "ram_gb": 1},
    },
    "cody": {
        "label": "Sourcegraph Cody",
        "color": "#FF5543",
        "invoke_mode": "arg",
        "cmd": ["cody", "chat", "--message", "{prompt}"],
        "capabilities": {"languages": ["python","javascript","go","java"],
                         "specializations": ["code-search","refactoring"]},
        "resources": {"vram_gb": 0, "ram_gb": 2},
    },
    "cursor": {
        "label": "Cursor",
        "color": "#0EA5E9",
        "invoke_mode": "note",
        "cmd": [],
        "capabilities": {"languages": ["python","javascript","typescript"],
                         "specializations": ["editor","autocomplete"]},
        "resources": {"vram_gb": 0, "ram_gb": 4},
    },
    "gh": {
        "label": "GitHub Copilot",
        "color": "#238636",
        "invoke_mode": "arg",
        "cmd": ["gh", "copilot", "suggest", "--target", "shell", "{prompt}"],
        "capabilities": {"languages": ["python","javascript","typescript","go","java"],
                         "specializations": ["copilot","completion"]},
        "resources": {"vram_gb": 0, "ram_gb": 2},
    },
}

# ✅ FIX 5.4: Ensure KNOWN_CLI_TOOLS and TOOL_PROFILES stay in sync
assert set(t["name"] for t in KNOWN_CLI_TOOLS) == set(TOOL_PROFILES.keys()), \
    "KNOWN_CLI_TOOLS and TOOL_PROFILES are out of sync"


def get_server_config() -> ServerConfig:
    """Get server configuration with validation."""
    return ServerConfig()


def get_agent_config(tool_name: str, ws_url: Optional[str] = None) -> AgentConfig:
    """Get agent configuration for a specific tool."""
    cfg = AgentConfig(tool_name=tool_name)
    if ws_url:
        cfg.ws_url = ws_url
    return cfg
