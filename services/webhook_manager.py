"""
DevMesh Webhook Notification System
-----------------------------------
Async HTTP webhooks for task events, with retry logic and delivery tracking.
"""

import asyncio
import time
import httpx
from typing import Dict, Optional, List, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

log = logging.getLogger("devmesh.webhooks")


__all__ = [
    "WebhookEvent",
    "WebhookDelivery",
    "WebhookManager",
    "get_webhook_manager",
]


class WebhookEvent(str, Enum):
    """Webhook event types."""

    TASK_CREATED = "task.created"
    TASK_CLAIMED = "task.claimed"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_ABANDONED = "task.abandoned"
    AGENT_CONNECTED = "agent.connected"
    AGENT_DISCONNECTED = "agent.disconnected"
    ERROR_OCCURRED = "error.occurred"


@dataclass
class WebhookDelivery:
    """Record of a webhook delivery attempt."""

    webhook_id: str
    event: WebhookEvent
    timestamp: str
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    error: Optional[str] = None
    retry_count: int = 0
    next_retry: Optional[str] = None
    success: bool = False


class WebhookManager:
    """Manages webhook registrations and delivery."""

    def __init__(self):
        self.webhooks: Dict[str, Dict[str, Any]] = {}
        self.deliveries: List[WebhookDelivery] = []
        self.delivery_callbacks: List[Callable] = []
        self._client = httpx.AsyncClient(timeout=10.0)
        self._retry_task: Optional[asyncio.Task] = None

    def register_webhook(
        self,
        webhook_id: str,
        url: str,
        events: List[WebhookEvent],
        headers: Optional[Dict[str, str]] = None,
        active: bool = True,
    ) -> None:
        """Register a webhook endpoint."""
        self.webhooks[webhook_id] = {
            "id": webhook_id,
            "url": url,
            "events": events,
            "headers": headers or {},
            "active": active,
            "created_at": datetime.now().isoformat(),
            "last_delivery": None,
            "delivery_count": 0,
        }
        log.info(f"Webhook registered: {webhook_id} -> {url}")

    def unregister_webhook(self, webhook_id: str) -> bool:
        """Unregister a webhook."""
        if webhook_id in self.webhooks:
            del self.webhooks[webhook_id]
            log.info(f"Webhook unregistered: {webhook_id}")
            return True
        return False

    def disable_webhook(self, webhook_id: str) -> bool:
        """Disable a webhook without removing it."""
        if webhook_id in self.webhooks:
            self.webhooks[webhook_id]["active"] = False
            return True
        return False

    def enable_webhook(self, webhook_id: str) -> bool:
        """Enable a webhook."""
        if webhook_id in self.webhooks:
            self.webhooks[webhook_id]["active"] = True
            return True
        return False

    async def fire(
        self,
        event: WebhookEvent,
        data: Dict[str, Any],
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        """Fire a webhook event to all registered handlers."""
        payload = {
            "event": event.value,
            "timestamp": datetime.now().isoformat(),
            "data": data,
            "tags": tags or {},
        }

        # Find matching webhooks
        matching_webhooks = [
            (wid, wh) for wid, wh in self.webhooks.items() if wh["active"] and event in wh["events"]
        ]

        if not matching_webhooks:
            return

        # Fire all matching webhooks asynchronously
        tasks = [self._deliver_webhook(wid, wh, payload) for wid, wh in matching_webhooks]

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _deliver_webhook(
        self,
        webhook_id: str,
        webhook: Dict[str, Any],
        payload: Dict[str, Any],
        retry_count: int = 0,
        max_retries: int = 3,
    ) -> WebhookDelivery:
        """Deliver a webhook with retry logic."""
        url = webhook["url"]
        headers = {"Content-Type": "application/json", **webhook.get("headers", {})}

        delivery = WebhookDelivery(
            webhook_id=webhook_id,
            event=WebhookEvent(payload["event"]),
            timestamp=payload["timestamp"],
            retry_count=retry_count,
        )

        try:
            start_time = time.time()

            # Use httpx for async HTTP
            response = await self._client.post(url, json=payload, headers=headers)

            response_time_ms = (time.time() - start_time) * 1000
            delivery.response_time_ms = response_time_ms
            delivery.status_code = response.status_code

            if response.status_code in (200, 201, 202, 204):
                delivery.success = True
                webhook["last_delivery"] = datetime.now().isoformat()
                webhook["delivery_count"] = webhook.get("delivery_count", 0) + 1
                log.info(
                    f"Webhook delivered: {webhook_id} ({response.status_code}) "
                    f"in {response_time_ms:.0f}ms"
                )
            else:
                # Retry on non-2xx responses
                if retry_count < max_retries:
                    delivery.next_retry = datetime.now().isoformat()
                    # Exponential backoff: 2^retry_count seconds
                    backoff = 2**retry_count
                    await asyncio.sleep(backoff)
                    return await self._deliver_webhook(
                        webhook_id, webhook, payload, retry_count + 1, max_retries
                    )
                else:
                    delivery.error = f"HTTP {response.status_code}"
                    log.warning(
                        f"Webhook delivery failed after {max_retries} retries: "
                        f"{webhook_id} -> {url}"
                    )

        except asyncio.TimeoutError:
            delivery.error = "Request timeout"
            log.error(f"Webhook timeout: {webhook_id} -> {url}")

            # Retry on timeout
            if retry_count < max_retries:
                delivery.next_retry = datetime.now().isoformat()
                backoff = 2**retry_count
                await asyncio.sleep(backoff)
                return await self._deliver_webhook(
                    webhook_id, webhook, payload, retry_count + 1, max_retries
                )

        except Exception as e:
            delivery.error = str(e)
            log.error(f"Webhook error: {webhook_id} -> {url}: {e}")

        # Store delivery record
        self.deliveries.append(delivery)
        if len(self.deliveries) > 1000:
            self.deliveries = self.deliveries[-1000:]

        # Notify callbacks
        for callback in self.delivery_callbacks:
            try:
                callback(delivery)
            except Exception as e:
                log.error(f"Webhook callback error: {e}")

        return delivery

    def register_delivery_callback(self, callback: Callable) -> None:
        """Register a callback to be called on webhook delivery."""
        self.delivery_callbacks.append(callback)

    def get_recent_deliveries(
        self,
        webhook_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[WebhookDelivery]:
        """Get recent webhook deliveries."""
        deliveries = self.deliveries

        if webhook_id:
            deliveries = [d for d in deliveries if d.webhook_id == webhook_id]

        return deliveries[-limit:]

    async def shutdown(self) -> None:
        """Shutdown the webhook manager."""
        await self._client.aclose()


# Global webhook manager instance
_webhook_manager: Optional[WebhookManager] = None


def get_webhook_manager() -> WebhookManager:
    """Get the global webhook manager instance."""
    global _webhook_manager
    if _webhook_manager is None:
        _webhook_manager = WebhookManager()
    return _webhook_manager
