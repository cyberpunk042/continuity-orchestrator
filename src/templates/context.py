"""
Template Context — Build safe rendering context.
"""

from __future__ import annotations

from typing import Dict, Any

from ..models.state import State
from ..policy.models import ActionDefinition


def build_template_context(
    state: State,
    action: ActionDefinition,
    tick_id: str,
) -> Dict[str, Any]:
    """
    Build a safe context for template rendering.

    This context is:
    - Read-only
    - Contains no secrets
    - Contains no renewal entry points
    - Contains only information safe for public templates
    """
    return {
        # Meta
        "project": state.meta.project,
        "plan_id": state.meta.plan_id,
        "tick_id": tick_id,
        "now_iso": state.timer.now_iso,

        # Stage info
        "stage": state.escalation.state,
        "stage_entered_at": state.escalation.state_entered_at_iso,

        # Safe timing info
        "time_to_deadline_minutes": state.timer.time_to_deadline_minutes,
        "time_to_deadline_hours": (
            state.timer.time_to_deadline_minutes // 60
            if state.timer.time_to_deadline_minutes else 0
        ),
        "overdue_minutes": state.timer.overdue_minutes,
        "overdue_hours": (
            state.timer.overdue_minutes // 60
            if state.timer.overdue_minutes else 0
        ),

        # Signals (safe public info)
        "mode": state.mode.name,
        "armed": state.mode.armed,

        # Action context
        "action_id": action.id,
        "action_channel": action.channel,

        # Safe labels (for static text blocks)
        "labels": {
            "project_name": "Continuity Orchestrator",
            "system_type": "Automated Continuity System",
        },
    }


def build_email_context(
    state: State,
    action: ActionDefinition,
    tick_id: str,
    channel: str,
) -> Dict[str, Any]:
    """
    Extended context for email templates.

    Adds recipient information appropriate for the channel.
    """
    base = build_template_context(state, action, tick_id)

    if channel == "operator":
        base["recipient_type"] = "operator"
    elif channel == "custodians":
        base["recipient_type"] = "custodian"
        base["recipients_count"] = len(state.integrations.routing.custodian_emails)

    return base
