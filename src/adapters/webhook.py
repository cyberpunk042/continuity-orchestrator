"""
Webhook Adapter — POST to external URLs.

This is the simplest real adapter - sends HTTP POST requests
to configured webhook URLs with a JSON payload.

## Configuration

Webhooks are configured in state.integrations.routing.observer_webhooks.

## Payload Format

{
    "event": "continuity_tick",
    "tick_id": "T-20260204T120000-ABC123",
    "stage": "PARTIAL",
    "timestamp": "2026-02-04T12:00:00Z",
    "data": {
        "state_id": "S-001",
        "time_to_deadline_minutes": 0,
        "overdue_minutes": 30,
        ...
    }
}

## Environment Variables

- WEBHOOK_TIMEOUT_SECONDS: Request timeout (default: 10)
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional
from uuid import uuid4

from .base import Adapter, ExecutionContext
from ..models.receipt import Receipt

logger = logging.getLogger(__name__)

# Optional httpx import — graceful degradation if not installed
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None


class WebhookAdapter(Adapter):
    """
    Real webhook adapter using httpx.
    
    Sends POST requests to configured webhook URLs.
    """
    
    def __init__(self, timeout: int = 10):
        self.timeout = int(os.environ.get("WEBHOOK_TIMEOUT_SECONDS", timeout))
    
    @property
    def name(self) -> str:
        return "webhook"
    
    def is_enabled(self, context: ExecutionContext) -> bool:
        """Enabled if httpx is available and webhooks are configured."""
        if not HTTPX_AVAILABLE:
            logger.warning("httpx not installed, webhook adapter disabled")
            return False
        
        webhooks = context.routing.observer_webhooks
        return len(webhooks) > 0
    
    def validate(self, context: ExecutionContext) -> tuple:
        """Validate webhook URLs are present."""
        webhooks = context.routing.observer_webhooks
        if not webhooks:
            return False, "No webhook URLs configured"
        return True, None
    
    def execute(self, context: ExecutionContext) -> Receipt:
        """Send POST to all configured webhooks."""
        webhooks: List[str] = context.routing.observer_webhooks
        
        if not webhooks:
            return Receipt.skipped(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                reason="no_webhooks_configured",
            )
        
        # Build payload
        payload = self._build_payload(context)
        
        # Track results
        successful = []
        failed = []
        
        for url in webhooks:
            try:
                response = httpx.post(
                    url,
                    json=payload,
                    timeout=self.timeout,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "continuity-orchestrator/1.0",
                    },
                )
                
                if response.status_code < 400:
                    successful.append(url)
                    logger.info(f"Webhook POST to {url}: {response.status_code}")
                else:
                    failed.append({"url": url, "status": response.status_code})
                    logger.warning(f"Webhook POST to {url} failed: {response.status_code}")
                    
            except httpx.TimeoutException:
                failed.append({"url": url, "error": "timeout"})
                logger.error(f"Webhook POST to {url} timed out")
            except httpx.RequestError as e:
                failed.append({"url": url, "error": str(e)})
                logger.error(f"Webhook POST to {url} failed: {e}")
        
        # Determine overall result
        if successful and not failed:
            return Receipt.ok(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                delivery_id=f"webhook_{uuid4().hex[:8]}",
                details={
                    "urls_sent": len(successful),
                    "payload_size": len(json.dumps(payload)),
                },
            )
        elif successful and failed:
            # Partial success
            return Receipt.ok(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                delivery_id=f"webhook_{uuid4().hex[:8]}",
                details={
                    "urls_sent": len(successful),
                    "urls_failed": len(failed),
                    "failures": failed,
                },
            )
        else:
            # All failed
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="all_webhooks_failed",
                error_message=f"All {len(failed)} webhooks failed",
                retryable=True,
            )
    
    def _build_payload(self, context: ExecutionContext) -> dict:
        """Build the webhook payload."""
        return {
            "event": "continuity_tick",
            "tick_id": context.tick_id,
            "stage": context.escalation.state,
            "timestamp": context.timer.now_iso,
            "action_id": context.action.id,
            "data": {
                "state_id": context.meta.state_id,
                "project": context.meta.project,
                "plan_id": context.meta.plan_id,
                "policy_version": context.meta.policy_version,
                "time_to_deadline_minutes": context.timer.time_to_deadline_minutes,
                "overdue_minutes": context.timer.overdue_minutes,
                "deadline_iso": context.timer.deadline_iso,
                "mode": context.state.mode.name,
                "armed": context.state.mode.armed,
            },
        }
