"""
DevMesh Error Handling
----------------------
Custom exception hierarchy for better error management.
"""

__all__ = [
    "DevMeshError",
    "AgentError",
    "AgentNotRegistered",
    "AgentSuspended",
    "LockError",
    "LockConflict",
    "LockTimeout",
    "TaskError",
    "TaskNotFound",
    "TaskStateError",
    "DependencyError",
    "ToolError",
    "ToolNotFound",
    "ToolInvokeError",
    "ResourceError",
    "InsufficientResources",
    "ConfigError",
    "InvalidConfiguration",
]


class DevMeshError(Exception):
    """Base exception for all DevMesh errors."""
    
    def __init__(self, message: str, error_code: str = "UNKNOWN", details: dict = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> dict:
        """Convert exception to dictionary for JSON responses."""
        return {
            "error": self.__class__.__name__,
            "code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class AgentError(DevMeshError):
    """Agent-related errors."""
    pass


class AgentNotRegistered(AgentError):
    """Agent is not registered."""
    
    def __init__(self, model: str):
        super().__init__(
            f"Agent '{model}' is not registered",
            "AGENT_NOT_REGISTERED",
            {"model": model}
        )


class AgentSuspended(AgentError):
    """Agent is suspended due to resource constraints."""
    
    def __init__(self, model: str, reason: str = ""):
        super().__init__(
            f"Agent '{model}' is suspended: {reason}",
            "AGENT_SUSPENDED",
            {"model": model, "reason": reason}
        )


class LockError(DevMeshError):
    """Lock management errors."""
    pass


class LockConflict(LockError):
    """Cannot acquire lock due to conflict."""
    
    def __init__(self, target: str, reason: str = ""):
        super().__init__(
            f"Cannot acquire lock on '{target}': {reason}",
            "LOCK_CONFLICT",
            {"target": target, "reason": reason}
        )


class LockTimeout(LockError):
    """Lock acquisition timed out."""
    
    def __init__(self, target: str, model: str):
        super().__init__(
            f"Lock timeout on '{target}' for agent '{model}'",
            "LOCK_TIMEOUT",
            {"target": target, "model": model}
        )


class TaskError(DevMeshError):
    """Task-related errors."""
    pass


class TaskNotFound(TaskError):
    """Task not found."""
    
    def __init__(self, task_id: str):
        super().__init__(
            f"Task '{task_id}' not found",
            "TASK_NOT_FOUND",
            {"task_id": task_id}
        )


class TaskStateError(TaskError):
    """Invalid task state transition."""
    
    def __init__(self, task_id: str, current_state: str, attempted_action: str):
        super().__init__(
            f"Cannot {attempted_action} task in '{current_state}' state",
            "TASK_STATE_ERROR",
            {"task_id": task_id, "current_state": current_state, "action": attempted_action}
        )


class DependencyError(TaskError):
    """Task dependencies not satisfied."""
    
    def __init__(self, task_id: str, unsatisfied_deps: list):
        super().__init__(
            f"Task '{task_id}' has unsatisfied dependencies: {', '.join(unsatisfied_deps)}",
            "DEPENDENCY_ERROR",
            {"task_id": task_id, "unsatisfied_deps": unsatisfied_deps}
        )


class ToolError(DevMeshError):
    """AI tool-related errors."""
    pass


class ToolNotFound(ToolError):
    """Tool not found or not detected."""
    
    def __init__(self, tool_name: str):
        super().__init__(
            f"Tool '{tool_name}' not found or not detected in PATH",
            "TOOL_NOT_FOUND",
            {"tool": tool_name}
        )


class ToolInvokeError(ToolError):
    """Error invoking a tool."""
    
    def __init__(self, tool_name: str, reason: str):
        super().__init__(
            f"Failed to invoke tool '{tool_name}': {reason}",
            "TOOL_INVOKE_ERROR",
            {"tool": tool_name, "reason": reason}
        )


class ResourceError(DevMeshError):
    """Resource allocation errors."""
    pass


class InsufficientResources(ResourceError):
    """Not enough resources available."""
    
    def __init__(self, model: str, requested: dict, available: dict):
        msg = f"Insufficient resources for agent '{model}'"
        super().__init__(
            msg,
            "INSUFFICIENT_RESOURCES",
            {"model": model, "requested": requested, "available": available}
        )


class ConfigError(DevMeshError):
    """Configuration errors."""
    pass


class InvalidConfiguration(ConfigError):
    """Invalid configuration value."""
    
    def __init__(self, param: str, value, reason: str = ""):
        super().__init__(
            f"Invalid configuration for '{param}': {value} ({reason})",
            "INVALID_CONFIG",
            {"param": param, "value": value, "reason": reason}
        )
