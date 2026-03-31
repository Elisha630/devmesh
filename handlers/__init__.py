"""
DevMesh WebSocket Handlers
--------------------------
WebSocket connection handlers for agents and dashboard.
"""

from handlers.agent_handler import AgentWebSocketHandler
from handlers.dashboard_handler import DashboardWebSocketHandler

__all__ = [
    "AgentWebSocketHandler",
    "DashboardWebSocketHandler",
]
