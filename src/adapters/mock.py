"""
Mock Adapters — Non-executing adapters for testing.

These log what would happen without actually sending emails, webhooks, etc.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from ..models.receipt import Receipt
from .base import Adapter, ExecutionContext

logger = logging.getLogger(__name__)


class MockAdapter(Adapter):
    """
    Generic mock adapter that logs actions without executing them.
    """

    def __init__(self, adapter_name: str = "mock"):
        self._name = adapter_name

    @property
    def name(self) -> str:
        return self._name

    def is_enabled(self, context: ExecutionContext) -> bool:
        # Mock is always enabled
        return True

    def validate(self, context: ExecutionContext) -> tuple:
        # Mock always validates
        return True, None

    def execute(self, context: ExecutionContext) -> Receipt:
        delivery_id = f"mock_{uuid4().hex[:8]}"

        logger.info(
            f"[MOCK:{self._name}] Would execute action '{context.action.id}' "
            f"on channel '{context.action.channel}' "
            f"at stage '{context.escalation.state}'"
        )

        if context.action.template:
            logger.info(f"  Template: {context.action.template}")

        return Receipt.ok(
            adapter=self.name,
            action_id=context.action.id,
            channel=context.action.channel,
            delivery_id=delivery_id,
            details={
                "mock": True,
                "stage": context.escalation.state,
                "template": context.action.template,
            },
        )


class MockEmailAdapter(MockAdapter):
    """Mock email adapter with email-specific logging."""

    def __init__(self):
        super().__init__("email")

    def execute(self, context: ExecutionContext) -> Receipt:
        if context.action.channel == "operator":
            to = context.routing.operator_email
        elif context.action.channel == "custodians":
            to = ", ".join(context.routing.custodian_emails)
        else:
            to = "unknown"

        logger.info(
            f"[MOCK:email] Would send to: {to}\n"
            f"  Template: {context.action.template}"
        )

        return Receipt.ok(
            adapter="email",
            action_id=context.action.id,
            channel=context.action.channel,
            delivery_id=f"mock_email_{uuid4().hex[:8]}",
            details={"to": to, "template": context.action.template},
        )


class MockSMSAdapter(MockAdapter):
    """Mock SMS adapter."""

    def __init__(self):
        super().__init__("sms")

    def execute(self, context: ExecutionContext) -> Receipt:
        to = context.routing.operator_sms

        logger.info(f"[MOCK:sms] Would send to: {to}")

        return Receipt.ok(
            adapter="sms",
            action_id=context.action.id,
            channel=context.action.channel,
            delivery_id=f"mock_sms_{uuid4().hex[:8]}",
            details={"to": to},
        )


class MockWebhookAdapter(MockAdapter):
    """Mock webhook adapter."""

    def __init__(self):
        super().__init__("webhook")

    def execute(self, context: ExecutionContext) -> Receipt:
        urls = context.routing.observer_webhooks

        logger.info(f"[MOCK:webhook] Would POST to {len(urls)} webhook(s)")

        return Receipt.ok(
            adapter="webhook",
            action_id=context.action.id,
            channel=context.action.channel,
            delivery_id=f"mock_webhook_{uuid4().hex[:8]}",
            details={"urls": urls, "payload": context.action.payload},
        )


class MockGitHubSurfaceAdapter(MockAdapter):
    """Mock GitHub surface adapter."""

    def __init__(self):
        super().__init__("github_surface")

    def execute(self, context: ExecutionContext) -> Receipt:
        artifact = context.action.artifact or {}

        logger.info(
            f"[MOCK:github_surface] Would create artifact:\n"
            f"  Type: {artifact.get('type', 'unknown')}\n"
            f"  Visibility: {artifact.get('visibility', 'unknown')}"
        )

        return Receipt.ok(
            adapter="github_surface",
            action_id=context.action.id,
            channel=context.action.channel,
            delivery_id=f"mock_gh_{uuid4().hex[:8]}",
            details={"artifact": artifact},
        )
