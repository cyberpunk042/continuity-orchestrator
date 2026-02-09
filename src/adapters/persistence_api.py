"""
Persistence API Adapter — Backup state to external API.

This adapter sends state snapshots to an external persistence service
for redundant backup and potential recovery.

## Configuration

- PERSISTENCE_API_URL: URL of the persistence API endpoint
- PERSISTENCE_API_KEY: API key for authentication

## Payload Format

{
    "event": "state_snapshot",
    "tick_id": "T-20260204T120000-ABC123",
    "timestamp": "2026-02-04T12:00:00Z",
    "state": { ... full state object ... },
    "metadata": {
        "project": "...",
        "escalation_state": "...",
        "policy_version": 1
    }
}
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from ..models.receipt import Receipt
from .base import Adapter, ExecutionContext

logger = logging.getLogger(__name__)

# Optional httpx import
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None


class PersistenceAPIAdapter(Adapter):
    """
    Adapter for persisting state to an external API.
    
    Useful for:
    - Redundant state backup
    - External monitoring systems
    - State recovery in case of repository issues
    """
    
    def __init__(self, timeout: int = 30):
        self.api_url = os.environ.get("PERSISTENCE_API_URL")
        self.api_key = os.environ.get("PERSISTENCE_API_KEY")
        self.timeout = int(os.environ.get("PERSISTENCE_API_TIMEOUT", timeout))
    
    @property
    def name(self) -> str:
        return "persistence_api"
    
    def is_enabled(self, context: ExecutionContext) -> bool:
        """Enabled if httpx available and API configured."""
        if not HTTPX_AVAILABLE:
            logger.warning("httpx not installed, persistence API disabled")
            return False
        
        if not self.api_url:
            logger.debug("PERSISTENCE_API_URL not set, persistence API disabled")
            return False
        
        try:
            return context.state.integrations.enabled_adapters.persistence_api
        except AttributeError:
            return True
    
    def validate(self, context: ExecutionContext) -> tuple:
        """Validate API configuration."""
        if not self.api_url:
            return False, "PERSISTENCE_API_URL not configured"
        
        # Basic URL validation
        if not self.api_url.startswith(("http://", "https://")):
            return False, f"Invalid API URL: {self.api_url}"
        
        return True, None
    
    def execute(self, context: ExecutionContext) -> Receipt:
        """Send state snapshot to persistence API."""
        payload = self._build_payload(context)
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "continuity-orchestrator/1.0",
        }
        
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        try:
            response = httpx.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            
            if response.status_code < 400:
                # Try to get response ID if available
                try:
                    resp_data = response.json()
                    snapshot_id = resp_data.get("id") or resp_data.get("snapshot_id")
                except Exception:
                    snapshot_id = None
                
                delivery_id = snapshot_id or f"persist_{uuid4().hex[:8]}"
                
                logger.info(f"State persisted: {delivery_id}")
                
                return Receipt.ok(
                    adapter=self.name,
                    action_id=context.action.id,
                    channel=context.action.channel,
                    delivery_id=delivery_id,
                    details={
                        "api_url": self.api_url,
                        "status_code": response.status_code,
                        "payload_size": len(json.dumps(payload)),
                    },
                )
            else:
                logger.error(f"Persistence API error: {response.status_code}")
                return Receipt.failed(
                    adapter=self.name,
                    action_id=context.action.id,
                    channel=context.action.channel,
                    error_code=f"api_{response.status_code}",
                    error_message=response.text[:200],
                    retryable=response.status_code >= 500,
                )
                
        except httpx.TimeoutException:
            logger.error("Persistence API request timed out")
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="timeout",
                error_message=f"Request timed out after {self.timeout}s",
                retryable=True,
            )
        except httpx.RequestError as e:
            logger.exception(f"Persistence API request failed: {e}")
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="request_error",
                error_message=str(e),
                retryable=True,
            )
    
    def _build_payload(self, context: ExecutionContext) -> dict:
        """Build the persistence payload."""
        # Get full state as dict
        state_dict = context.state.model_dump()
        
        return {
            "event": "state_snapshot",
            "tick_id": context.tick_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "state": state_dict,
            "metadata": {
                "project": context.meta.project,
                "state_id": context.meta.state_id,
                "escalation_state": context.escalation.state,
                "policy_version": context.meta.policy_version,
                "plan_id": context.meta.plan_id,
            },
        }
