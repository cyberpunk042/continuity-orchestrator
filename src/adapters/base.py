"""
Adapter Base Class — Interface for all adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from ..models.receipt import Receipt
from ..models.state import State
from ..policy.models import ActionDefinition


class ExecutionContext:
    """
    Context provided to adapters during execution.

    Contains everything an adapter needs to execute an action.
    """

    def __init__(
        self,
        state: State,
        action: ActionDefinition,
        tick_id: str,
        template_content: Optional[str] = None,
    ):
        self.state = state
        self.action = action
        self.tick_id = tick_id
        self.template_content = template_content

        # Convenience references
        self.routing = state.integrations.routing
        self.meta = state.meta
        self.timer = state.timer
        self.escalation = state.escalation

    def to_payload_dict(self) -> Dict[str, Any]:
        """Build the standard payload structure."""
        return {
            "meta": {
                "tick_id": self.tick_id,
                "state_id": self.state.meta.state_id,
                "policy_version": self.state.meta.policy_version,
                "plan_id": self.state.meta.plan_id,
                "escalation_state": self.escalation.state,
                "now_iso": self.timer.now_iso,
            },
            "action": {
                "action_id": self.action.id,
                "stage": self.escalation.state,
                "adapter": self.action.adapter,
                "channel": self.action.channel,
            },
            "routing": {
                "operator_email": self.routing.operator_email,
                "operator_sms": self.routing.operator_sms,
                "custodian_emails": self.routing.custodian_emails,
                "observer_webhooks": self.routing.observer_webhooks,
            },
            "data": {
                "time_to_deadline_minutes": self.timer.time_to_deadline_minutes,
                "overdue_minutes": self.timer.overdue_minutes,
            },
        }


class Adapter(ABC):
    """
    Abstract base class for all adapters.

    Adapters perform external side effects and return receipts.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The adapter identifier (e.g., 'email', 'webhook')."""
        pass

    @abstractmethod
    def is_enabled(self, context: ExecutionContext) -> bool:
        """Check if this adapter is enabled for the given context."""
        pass

    @abstractmethod
    def validate(self, context: ExecutionContext) -> tuple:
        """
        Validate that the action can be executed.

        Returns (is_valid, error_message).
        """
        pass

    @abstractmethod
    def execute(self, context: ExecutionContext) -> Receipt:
        """
        Execute the action and return a receipt.

        Should never raise exceptions; failures are captured in the receipt.
        """
        pass
