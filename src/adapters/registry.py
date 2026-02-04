"""
Adapter Registry — Lookup adapters by name.
"""

from __future__ import annotations

import logging
from typing import Dict

from .base import Adapter, ExecutionContext
from .mock import (
    MockAdapter,
    MockEmailAdapter,
    MockSMSAdapter,
    MockWebhookAdapter,
    MockGitHubSurfaceAdapter,
)
from ..models.receipt import Receipt
from ..policy.models import ActionDefinition


logger = logging.getLogger(__name__)


class AdapterRegistry:
    """
    Registry for adapter lookup by name.

    Supports mock mode where all adapters are mocks.
    """

    def __init__(self, mock_mode: bool = True):
        self.adapters: Dict[str, Adapter] = {}
        self.mock_mode = mock_mode
        self._fallback = MockAdapter("fallback")

        if mock_mode:
            self._register_mock_adapters()

    def _register_mock_adapters(self) -> None:
        """Register all mock adapters."""
        self.register(MockEmailAdapter())
        self.register(MockSMSAdapter())
        self.register(MockWebhookAdapter())
        self.register(MockGitHubSurfaceAdapter())
        self.register(MockAdapter("x"))
        self.register(MockAdapter("reddit"))
        self.register(MockAdapter("article_publish"))
        self.register(MockAdapter("persistence_api"))

    def register(self, adapter: Adapter) -> None:
        """Register an adapter."""
        self.adapters[adapter.name] = adapter
        logger.debug(f"Registered adapter: {adapter.name}")

    def get(self, name: str) -> Adapter:
        """Get an adapter by name, or fallback mock."""
        adapter = self.adapters.get(name)
        if adapter is None:
            logger.warning(f"No adapter registered for '{name}', using fallback")
            return self._fallback
        return adapter

    def execute_action(
        self,
        action: ActionDefinition,
        context: ExecutionContext,
    ) -> Receipt:
        """
        Execute an action through the appropriate adapter.

        Handles:
        - Adapter lookup
        - Enablement check
        - Validation
        - Execution
        - Error handling
        """
        adapter = self.get(action.adapter)

        # Check if enabled
        if not adapter.is_enabled(context):
            return Receipt.skipped(
                adapter=action.adapter,
                action_id=action.id,
                channel=action.channel,
                reason="adapter_disabled",
            )

        # Validate
        is_valid, error_msg = adapter.validate(context)
        if not is_valid:
            return Receipt.skipped(
                adapter=action.adapter,
                action_id=action.id,
                channel=action.channel,
                reason=f"validation_failed: {error_msg}",
            )

        # Execute
        try:
            return adapter.execute(context)
        except Exception as e:
            logger.exception(f"Adapter {action.adapter} failed: {e}")
            return Receipt.failed(
                adapter=action.adapter,
                action_id=action.id,
                channel=action.channel,
                error_code="adapter_exception",
                error_message=str(e),
                retryable=True,
            )
