"""
Adapter Registry — Lookup adapters by name.
"""

from __future__ import annotations

import logging
from typing import Dict

from ..models.receipt import Receipt
from ..policy.models import ActionDefinition
from .base import Adapter, ExecutionContext
from .mock import (
    MockAdapter,
    MockEmailAdapter,
    MockGitHubSurfaceAdapter,
    MockSMSAdapter,
    MockWebhookAdapter,
)

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """
    Registry for adapter lookup by name.

    Supports mock mode where all adapters are mocks.
    When mock_mode is False, registers real adapters.
    """

    def __init__(self, mock_mode: bool = True):
        self.adapters: Dict[str, Adapter] = {}
        self.mock_mode = mock_mode
        self._fallback = MockAdapter("fallback")

        if mock_mode:
            self._register_mock_adapters()
        else:
            self._register_real_adapters()

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

    def _register_real_adapters(self) -> None:
        """Register real adapters (with mock fallbacks for unimplemented)."""
        import os
        
        # Webhook adapter
        try:
            from .webhook import WebhookAdapter
            self.register(WebhookAdapter())
            logger.info("Registered real webhook adapter")
        except ImportError:
            self.register(MockWebhookAdapter())
            logger.warning("httpx not available, using mock webhook")
        
        # Email adapter (Resend)
        if os.environ.get("RESEND_API_KEY"):
            try:
                from .email_resend import ResendEmailAdapter
                self.register(ResendEmailAdapter())
                logger.info("Registered Resend email adapter")
            except ImportError:
                self.register(MockEmailAdapter())
                logger.warning("resend package not available, using mock email")
        else:
            self.register(MockEmailAdapter())
            logger.debug("RESEND_API_KEY not set, using mock email")
        
        # GitHub Surface adapter
        if os.environ.get("GITHUB_TOKEN"):
            try:
                from .github_surface import GitHubSurfaceAdapter
                self.register(GitHubSurfaceAdapter())
                logger.info("Registered GitHub Surface adapter")
            except ImportError:
                self.register(MockGitHubSurfaceAdapter())
                logger.warning("httpx not available, using mock GitHub")
        else:
            self.register(MockGitHubSurfaceAdapter())
            logger.debug("GITHUB_TOKEN not set, using mock GitHub")
        
        # Persistence API adapter
        if os.environ.get("PERSISTENCE_API_URL"):
            try:
                from .persistence_api import PersistenceAPIAdapter
                self.register(PersistenceAPIAdapter())
                logger.info("Registered Persistence API adapter")
            except ImportError:
                self.register(MockAdapter("persistence_api"))
                logger.warning("httpx not available, using mock persistence")
        else:
            self.register(MockAdapter("persistence_api"))
            logger.debug("PERSISTENCE_API_URL not set, using mock persistence")
        
        # Article publish adapter (always available - uses site generator)
        try:
            from .article_publish import ArticlePublishAdapter
            self.register(ArticlePublishAdapter())
            logger.info("Registered Article Publish adapter")
        except ImportError as e:
            self.register(MockAdapter("article_publish"))
            logger.warning(f"Article publish not available: {e}")
        # SMS adapter (Twilio)
        twilio_configured = all([
            os.environ.get("TWILIO_ACCOUNT_SID"),
            os.environ.get("TWILIO_AUTH_TOKEN"),
            os.environ.get("TWILIO_FROM_NUMBER"),
        ])
        
        if twilio_configured:
            try:
                from .sms_twilio import TwilioSMSAdapter
                self.register(TwilioSMSAdapter())
                logger.info("Registered Twilio SMS adapter")
            except ImportError:
                self.register(MockSMSAdapter())
                logger.warning("twilio package not available, using mock SMS")
        else:
            self.register(MockSMSAdapter())
            logger.debug("Twilio credentials not set, using mock SMS")
        
        # X (Twitter) adapter
        x_configured = all([
            os.environ.get("X_API_KEY"),
            os.environ.get("X_API_SECRET"),
            os.environ.get("X_ACCESS_TOKEN"),
            os.environ.get("X_ACCESS_SECRET"),
        ])
        
        if x_configured:
            try:
                from .x_twitter import XAdapter
                self.register(XAdapter())
                logger.info("Registered X (Twitter) adapter")
            except ImportError:
                self.register(MockAdapter("x"))
                logger.warning("httpx not available, using mock X adapter")
        else:
            self.register(MockAdapter("x"))
            logger.debug("X API credentials not set, using mock X adapter")
        
        # Reddit adapter
        reddit_configured = all([
            os.environ.get("REDDIT_CLIENT_ID"),
            os.environ.get("REDDIT_CLIENT_SECRET"),
            os.environ.get("REDDIT_USERNAME"),
            os.environ.get("REDDIT_PASSWORD"),
        ])
        
        if reddit_configured:
            try:
                from .reddit import RedditAdapter
                self.register(RedditAdapter())
                logger.info("Registered Reddit adapter")
            except ImportError:
                self.register(MockAdapter("reddit"))
                logger.warning("praw not available, using mock Reddit adapter")
        else:
            self.register(MockAdapter("reddit"))
            logger.debug("Reddit credentials not set, using mock Reddit adapter")
        
        # Internet Archive adapter (always available - no auth required)
        try:
            from .internet_archive import InternetArchiveAdapter
            self.register(InternetArchiveAdapter())
            logger.info("Registered Internet Archive adapter")
        except ImportError as e:
            self.register(MockAdapter("archive"))
            logger.warning(f"Internet Archive adapter not available: {e}")

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
