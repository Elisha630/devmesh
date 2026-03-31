"""
DevMesh WebSocket Monitoring & Health
-------------------------------------
WebSocket ping/pong handling, connection timeouts, and health tracking.
"""

import asyncio
import time
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging

log = logging.getLogger("devmesh.ws_health")


__all__ = [
    "WebSocketHealth",
    "ConnectionMetrics",
    "HealthMonitor",
]


@dataclass
class ConnectionMetrics:
    """Metrics for a WebSocket connection."""
    client_id: str
    connected_at: str
    last_ping_sent: Optional[float] = None
    last_pong_received: Optional[float] = None
    ping_count: int = 0
    pong_count: int = 0
    latency_ms: float = 0.0
    message_count: int = 0
    error_count: int = 0
    is_healthy: bool = True
    disconnected_at: Optional[str] = None
    
    def update_latency(self, latency_ms: float) -> None:
        """Update connection latency."""
        # Use exponential moving average for smooth latency tracking
        if self.latency_ms == 0:
            self.latency_ms = latency_ms
        else:
            self.latency_ms = (self.latency_ms * 0.7) + (latency_ms * 0.3)
    
    def mark_error(self) -> None:
        """Increment error count and check health."""
        self.error_count += 1
        # Mark unhealthy if error rate is high
        if self.error_count > 10:
            self.is_healthy = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "client_id": self.client_id,
            "connected_at": self.connected_at,
            "latency_ms": round(self.latency_ms, 1),
            "ping_count": self.ping_count,
            "pong_count": self.pong_count,
            "message_count": self.message_count,
            "error_count": self.error_count,
            "is_healthy": self.is_healthy,
            "uptime_sec": self._get_uptime(),
        }
    
    def _get_uptime(self) -> float:
        """Get connection uptime in seconds."""
        try:
            start = datetime.fromisoformat(self.connected_at)
            duration = datetime.now() - start
            return duration.total_seconds()
        except Exception:
            return 0.0


class WebSocketHealth:
    """Monitors individual WebSocket connection health."""
    
    def __init__(self, client_id: str, ping_interval: float = 30.0, ping_timeout: float = 10.0):
        self.client_id = client_id
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.metrics = ConnectionMetrics(
            client_id=client_id,
            connected_at=datetime.now().isoformat(),
        )
        self._ping_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start_pinging(self) -> None:
        """Start sending periodic pings."""
        if self._running:
            return
        
        self._running = True
        self._ping_task = asyncio.create_task(self._ping_loop())
    
    async def _ping_loop(self) -> None:
        """Send pings at regular intervals."""
        while self._running:
            try:
                await asyncio.sleep(self.ping_interval)
                
                # Record ping sent time
                self.metrics.last_ping_sent = time.time()
                self.metrics.ping_count += 1
                
                # The actual ping will be sent by the caller
                # This just tracks the metrics
                
                # Check for pong timeout
                if self.metrics.last_pong_received is not None:
                    time_since_pong = time.time() - self.metrics.last_pong_received
                    if time_since_pong > self.ping_timeout:
                        log.warning(f"WebSocket {self.client_id}: No pong received for {time_since_pong:.1f}s")
                        self.metrics.mark_error()
                        # Connection likely dead; will be handled by caller
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Error in ping loop for {self.client_id}: {e}")
                self.metrics.mark_error()
    
    def on_pong_received(self) -> None:
        """Called when a pong is received."""
        now = time.time()
        self.metrics.last_pong_received = now
        self.metrics.pong_count += 1
        
        # Calculate latency
        if self.metrics.last_ping_sent:
            latency_ms = (now - self.metrics.last_ping_sent) * 1000
            self.metrics.update_latency(latency_ms)
            log.debug(f"WebSocket {self.client_id}: latency {latency_ms:.1f}ms")
    
    def on_message(self) -> None:
        """Called when a message is received."""
        self.metrics.message_count += 1
    
    def on_error(self) -> None:
        """Called when an error occurs."""
        self.metrics.mark_error()
    
    async def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
        
        self.metrics.disconnected_at = datetime.now().isoformat()
    
    def is_healthy(self) -> bool:
        """Check if connection is healthy."""
        return self.metrics.is_healthy


class HealthMonitor:
    """Monitors health of multiple WebSocket connections."""
    
    def __init__(self, ping_interval: float = 30.0, ping_timeout: float = 10.0):
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.connections: Dict[str, WebSocketHealth] = {}
        self.health_callbacks: list[Callable] = []
    
    def register_connection(self, client_id: str) -> WebSocketHealth:
        """Register a new connection."""
        health = WebSocketHealth(
            client_id,
            ping_interval=self.ping_interval,
            ping_timeout=self.ping_timeout,
        )
        self.connections[client_id] = health
        log.info(f"Registered connection: {client_id}")
        return health
    
    def unregister_connection(self, client_id: str) -> Optional[ConnectionMetrics]:
        """Unregister a connection and return its metrics."""
        if client_id in self.connections:
            health = self.connections.pop(client_id)
            asyncio.create_task(health.stop())
            log.info(f"Unregistered connection: {client_id}")
            return health.metrics
        return None
    
    def get_health(self, client_id: str) -> Optional[WebSocketHealth]:
        """Get health monitor for a connection."""
        return self.connections.get(client_id)
    
    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all connections."""
        return {
            cid: health.metrics.to_dict()
            for cid, health in self.connections.items()
        }
    
    def get_healthy_count(self) -> int:
        """Get count of healthy connections."""
        return sum(1 for h in self.connections.values() if h.is_healthy())
    
    def get_unhealthy_connections(self) -> list[str]:
        """Get list of unhealthy connection IDs."""
        return [
            cid for cid, health in self.connections.items()
            if not health.is_healthy()
        ]
    
    def register_callback(self, callback: Callable) -> None:
        """Register callback for health events."""
        self.health_callbacks.append(callback)
    
    async def check_all_health(self) -> Dict[str, bool]:
        """Check health of all connections."""
        health_status = {}
        
        for cid, health in self.connections.items():
            is_healthy = health.is_healthy()
            health_status[cid] = is_healthy
            
            if not is_healthy:
                log.warning(f"Unhealthy connection detected: {cid}")
                
                # Notify callbacks
                for callback in self.health_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(cid, health.metrics)
                        else:
                            callback(cid, health.metrics)
                    except Exception as e:
                        log.error(f"Error in health callback: {e}")
        
        return health_status
    
    async def cleanup_dead_connections(self, timeout_sec: float = 300) -> int:
        """Remove connections that have been inactive for too long."""
        now = time.time()
        dead_connections = []
        
        for cid, health in self.connections.items():
            if health.metrics.disconnected_at:
                continue  # Already stopped
            
            if health.metrics.last_pong_received is None:
                continue  # Never received pong
            
            time_since_activity = now - health.metrics.last_pong_received
            if time_since_activity > timeout_sec:
                dead_connections.append(cid)
                log.info(f"Cleaning up dead connection: {cid} (inactive for {time_since_activity:.0f}s)")
        
        for cid in dead_connections:
            await health.stop()
            self.connections.pop(cid, None)
        
        return len(dead_connections)


# Global health monitor instance
_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor(ping_interval: float = 30.0, ping_timeout: float = 10.0) -> HealthMonitor:
    """Get the global health monitor instance."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor(ping_interval, ping_timeout)
    return _health_monitor
