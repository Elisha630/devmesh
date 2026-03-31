"""
DevMesh Configuration Manager
------------------------------
Pydantic-based configuration with YAML/TOML support, runtime reload, and per-tool overrides.
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

try:
    from pydantic import BaseModel, Field, validator, root_validator

    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

try:
    import tomllib

    TOML_AVAILABLE = True
except ImportError:
    try:
        import tomli as tomllib

        TOML_AVAILABLE = True
    except ImportError:
        TOML_AVAILABLE = False


__all__ = [
    "ServerConfigModel",
    "ToolConfigModel",
    "ConfigManager",
    "get_config_manager",
]


if PYDANTIC_AVAILABLE:

    class ServerConfigModel(BaseModel):
        """Pydantic server configuration with validation."""

        # Network
        ws_host: str = Field(default="127.0.0.1", description="WebSocket server host")
        ws_port: int = Field(default=7700, description="WebSocket server port", ge=1, le=65535)
        dashboard_port: int = Field(default=7702, description="Dashboard port", ge=1, le=65535)
        http_port: int = Field(default=7701, description="HTTP server port", ge=1, le=65535)

        # Timeouts
        lock_ttl_sec: int = Field(default=15, description="Lock TTL in seconds", ge=1)
        heartbeat_grace_sec: int = Field(
            default=5, description="Heartbeat grace period in seconds", ge=1
        )
        agent_reconnect_grace_sec: int = Field(
            default=30, description="Agent reconnect grace in seconds", ge=1
        )
        heartbeat_interval_sec: int = Field(
            default=4, description="Heartbeat interval in seconds", ge=1
        )
        ai_cli_version_timeout_sec: int = Field(
            default=3, description="CLI version check timeout", ge=1
        )
        ai_cli_invoke_timeout_sec: int = Field(default=120, description="CLI invoke timeout", ge=1)
        ws_ping_interval_sec: int = Field(default=30, description="WebSocket ping interval", ge=5)
        ws_ping_timeout_sec: int = Field(default=10, description="WebSocket ping timeout", ge=1)

        # Storage
        audit_dir: str = Field(default=".devmesh", description="Audit log directory")
        audit_log_file: str = Field(default="audit.jsonl", description="Audit log filename")

        # Hardware
        gpu_vram_gb: float = Field(default=16.0, description="GPU VRAM in GB", ge=0.1)
        ram_gb: float = Field(default=32.0, description="System RAM in GB", ge=0.1)

        # Feature flags
        enable_result_caching: bool = Field(default=True, description="Enable result caching")
        enable_webhooks: bool = Field(default=False, description="Enable webhook notifications")
        enable_file_watching: bool = Field(default=True, description="Enable file watching")
        enable_task_templates: bool = Field(default=True, description="Enable task templates")

        # Caching
        cache_ttl_sec: int = Field(default=3600, description="Cache TTL in seconds", ge=1)
        cache_max_size_mb: int = Field(default=100, description="Max cache size in MB", ge=1)

        # UI
        auto_open_browser: bool = Field(default=True, description="Auto-open browser on startup")
        hardware_sample_interval_sec: float = Field(
            default=2.0, description="Hardware sample interval", ge=0.1
        )
        hardware_history_len: int = Field(default=120, description="Hardware history length", ge=10)

        # Conflict resolution
        conflict_resolve_cooldown_sec: int = Field(
            default=15, description="Conflict resolution cooldown", ge=1
        )

        # Logging
        log_level: str = Field(default="INFO", description="Log level")
        log_file: Optional[str] = Field(default=None, description="Log file path")

        # Monitoring
        enable_prometheus: bool = Field(default=True, description="Enable Prometheus metrics")
        metrics_port: int = Field(default=8000, description="Metrics port", ge=1, le=65535)

        @validator("log_level")
        def validate_log_level(cls, v):
            valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
            if v.upper() not in valid:
                raise ValueError(f"log_level must be one of {valid}")
            return v.upper()

        @root_validator
        def validate_ports_unique(cls, values):
            """Ensure all ports are unique."""
            ports = {
                "ws_port": values.get("ws_port"),
                "http_port": values.get("http_port"),
                "dashboard_port": values.get("dashboard_port"),
                "metrics_port": values.get("metrics_port"),
            }
            port_list = [v for v in ports.values() if v]
            if len(port_list) != len(set(port_list)):
                raise ValueError("All ports must be unique")
            return values

        class Config:
            env_prefix = "DEVMESH_"

else:
    # Fallback if Pydantic not available
    @dataclass
    class ServerConfigModel:
        """Fallback configuration without Pydantic."""

        ws_host: str = "127.0.0.1"
        ws_port: int = 7700
        dashboard_port: int = 7702
        http_port: int = 7701
        lock_ttl_sec: int = 15
        heartbeat_grace_sec: int = 5
        agent_reconnect_grace_sec: int = 30
        heartbeat_interval_sec: int = 4
        ai_cli_version_timeout_sec: int = 3
        ai_cli_invoke_timeout_sec: int = 120
        ws_ping_interval_sec: int = 30
        ws_ping_timeout_sec: int = 10
        audit_dir: str = ".devmesh"
        audit_log_file: str = "audit.jsonl"
        gpu_vram_gb: float = 16.0
        ram_gb: float = 32.0
        enable_result_caching: bool = True
        enable_webhooks: bool = False
        enable_file_watching: bool = True
        enable_task_templates: bool = True
        cache_ttl_sec: int = 3600
        cache_max_size_mb: int = 100
        auto_open_browser: bool = True
        hardware_sample_interval_sec: float = 2.0
        hardware_history_len: int = 120
        conflict_resolve_cooldown_sec: int = 15
        log_level: str = "INFO"
        log_file: Optional[str] = None
        enable_prometheus: bool = True
        metrics_port: int = 8000


if PYDANTIC_AVAILABLE:

    class ToolConfigModel(BaseModel):
        """Per-tool configuration overrides."""

        model_id: str
        enabled: bool = True
        max_concurrent: int = Field(default=1, ge=1)
        timeout_sec: int = Field(default=120, ge=1)
        resource_limits: Dict[str, Any] = Field(default_factory=dict)
        custom_env: Dict[str, str] = Field(default_factory=dict)
        webhook_url: Optional[str] = None

        class Config:
            extra = "allow"

else:

    @dataclass
    class ToolConfigModel:
        """Per-tool configuration overrides."""

        model_id: str
        enabled: bool = True
        max_concurrent: int = 1
        timeout_sec: int = 120
        resource_limits: Dict[str, Any] = field(default_factory=dict)
        custom_env: Dict[str, str] = field(default_factory=dict)
        webhook_url: Optional[str] = None


class ConfigManager:
    """Manages configuration with support for YAML/TOML, env vars, and runtime reload."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(os.getenv("DEVMESH_CONFIG_DIR", "."))
        self.server_config: ServerConfigModel = self._load_server_config()
        self.tool_configs: Dict[str, ToolConfigModel] = self._load_tool_configs()
        self._watchers: Dict[str, callable] = {}

    def _load_server_config(self) -> ServerConfigModel:
        """Load server config from environment, YAML, TOML, or defaults."""
        config_dict = self._merge_config_sources()

        if PYDANTIC_AVAILABLE:
            try:
                return ServerConfigModel(**config_dict)
            except Exception as e:
                raise ValueError(f"Invalid server configuration: {e}")
        else:
            # Fallback: apply environment variables directly
            return ServerConfigModel(**config_dict)

    def _load_tool_configs(self) -> Dict[str, ToolConfigModel]:
        """Load per-tool configuration overrides."""
        tool_configs = {}

        # Load from tools.yaml if exists
        tools_yaml = self.config_dir / "tools.yaml"
        if tools_yaml.exists() and YAML_AVAILABLE:
            try:
                with open(tools_yaml) as f:
                    data = yaml.safe_load(f) or {}
                    for tool_id, config in data.get("tools", {}).items():
                        config["model_id"] = tool_id
                        if PYDANTIC_AVAILABLE:
                            tool_configs[tool_id] = ToolConfigModel(**config)
                        else:
                            tool_configs[tool_id] = ToolConfigModel(**config)
            except Exception as e:
                print(f"Warning: Failed to load tools.yaml: {e}")

        # Load from tools.toml if exists
        tools_toml = self.config_dir / "tools.toml"
        if tools_toml.exists() and TOML_AVAILABLE:
            try:
                with open(tools_toml, "rb") as f:
                    data = tomllib.load(f) if hasattr(tomllib, "load") else json.loads(f.read())
                    for tool_id, config in data.get("tools", {}).items():
                        config["model_id"] = tool_id
                        if PYDANTIC_AVAILABLE:
                            tool_configs[tool_id] = ToolConfigModel(**config)
                        else:
                            tool_configs[tool_id] = ToolConfigModel(**config)
            except Exception as e:
                print(f"Warning: Failed to load tools.toml: {e}")

        return tool_configs

    def _merge_config_sources(self) -> Dict[str, Any]:
        """Merge configuration from YAML, TOML, and environment variables."""
        config = {}

        # Load from devmesh.yaml
        yaml_path = self.config_dir / "devmesh.yaml"
        if yaml_path.exists() and YAML_AVAILABLE:
            try:
                with open(yaml_path) as f:
                    yaml_config = yaml.safe_load(f) or {}
                    config.update(yaml_config)
            except Exception as e:
                print(f"Warning: Failed to load devmesh.yaml: {e}")

        # Load from devmesh.toml
        toml_path = self.config_dir / "devmesh.toml"
        if toml_path.exists() and TOML_AVAILABLE:
            try:
                with open(toml_path, "rb") as f:
                    toml_config = (
                        tomllib.load(f) if hasattr(tomllib, "load") else json.loads(f.read())
                    )
                    config.update(toml_config)
            except Exception as e:
                print(f"Warning: Failed to load devmesh.toml: {e}")

        # Override with environment variables (highest priority)
        env_overrides = {
            k.replace("DEVMESH_", "").lower(): v
            for k, v in os.environ.items()
            if k.startswith("DEVMESH_")
        }

        # Convert string values to appropriate types
        for key in ["ws_port", "http_port", "dashboard_port", "metrics_port"]:
            if key in env_overrides:
                try:
                    env_overrides[key] = int(env_overrides[key])
                except ValueError:
                    pass

        for key in ["gpu_vram_gb", "ram_gb", "hardware_sample_interval_sec"]:
            if key in env_overrides:
                try:
                    env_overrides[key] = float(env_overrides[key])
                except ValueError:
                    pass

        for key in [
            "enable_result_caching",
            "enable_webhooks",
            "enable_file_watching",
            "enable_task_templates",
            "auto_open_browser",
            "enable_prometheus",
        ]:
            if key in env_overrides:
                env_overrides[key] = env_overrides[key].lower() in ("true", "1", "yes")

        config.update(env_overrides)
        return config

    def reload(self) -> None:
        """Reload configuration from disk."""
        self.server_config = self._load_server_config()
        self.tool_configs = self._load_tool_configs()

        # Notify watchers
        for callback in self._watchers.values():
            try:
                callback(self)
            except Exception as e:
                print(f"Error in config watcher: {e}")

    def watch(self, name: str, callback: callable) -> None:
        """Register a callback to be called on config reload."""
        self._watchers[name] = callback

    def unwatch(self, name: str) -> None:
        """Unregister a callback."""
        self._watchers.pop(name, None)

    def get_tool_config(self, tool_id: str) -> Optional[ToolConfigModel]:
        """Get per-tool configuration."""
        return self.tool_configs.get(tool_id)


# Global config manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get the global config manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def init_config_manager(config_dir: Optional[Path] = None) -> ConfigManager:
    """Initialize the global config manager."""
    global _config_manager
    _config_manager = ConfigManager(config_dir)
    return _config_manager
