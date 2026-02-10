"""
State Models — Pydantic schemas for runtime state.

The state file (state/current.json) is the single source of truth
for the current countdown, escalation, and execution status.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class Meta(BaseModel):
    """Metadata about the state record."""

    schema_version: int = 1
    project: str = "continuity-orchestrator"
    state_id: str
    updated_at_iso: str
    policy_version: int = 1
    plan_id: str = "default"


class Mode(BaseModel):
    """Operating mode configuration."""

    name: Literal["renewable_countdown", "one_way_fuse", "manual_arm"] = "renewable_countdown"
    armed: bool = True


class Timer(BaseModel):
    """Countdown timer state."""

    deadline_iso: str
    grace_minutes: int = 0
    # Computed at tick start:
    now_iso: Optional[str] = None
    time_to_deadline_minutes: Optional[int] = None
    overdue_minutes: Optional[int] = None


class Renewal(BaseModel):
    """Renewal tracking."""

    last_renewal_iso: Optional[str] = None
    renewed_this_tick: bool = False
    renewal_count: int = 0


class Security(BaseModel):
    """Security and lockout state."""

    failed_attempts: int = 0
    lockout_active: bool = False
    lockout_until_iso: Optional[str] = None
    max_failed_attempts: int = 3
    attempt_window_seconds: int = 60


# Escalation state literal type
EscalationState = Literal["OK", "REMIND_1", "REMIND_2", "PRE_RELEASE", "PARTIAL", "FULL"]


class Escalation(BaseModel):
    """Escalation state machine."""

    state: EscalationState = "OK"
    state_entered_at_iso: str
    last_transition_rule_id: Optional[str] = None
    monotonic_enforced: bool = True


class ActionReceipt(BaseModel):
    """Summary of a previously executed action."""

    status: Literal["ok", "skipped", "failed"]
    last_delivery_id: Optional[str] = None
    last_executed_iso: str


class Actions(BaseModel):
    """Action execution tracking for idempotency."""

    executed: Dict[str, ActionReceipt] = Field(default_factory=dict)
    last_tick_actions: List[str] = Field(default_factory=list)


class ReleaseConfig(BaseModel):
    """Manual release trigger configuration."""
    
    # Release trigger state
    triggered: bool = False
    trigger_time_iso: Optional[str] = None
    target_stage: Optional[str] = None
    
    # Delay settings
    delay_minutes: int = 0  # 0 = immediate on next cron
    delay_scope: Literal["full", "site_only"] = "full"  # full = integrations + site, site_only = just site
    
    # Computed: when the release should execute
    execute_after_iso: Optional[str] = None
    
    # Client-side verification token (for fake success display)
    client_token: Optional[str] = None


class EnabledAdapters(BaseModel):
    """Adapter enable/disable flags."""

    email: bool = True
    sms: bool = True
    x: bool = True
    reddit: bool = True
    webhook: bool = True
    github_surface: bool = True
    article_publish: bool = True
    persistence_api: bool = True


class Routing(BaseModel):
    """Delivery routing configuration."""

    github_repository: Optional[str] = None
    operator_email: str
    operator_sms: Optional[str] = None
    custodian_emails: List[str] = Field(default_factory=list)
    subscriber_emails: List[str] = Field(default_factory=list)
    observer_webhooks: List[str] = Field(default_factory=list)
    reddit_targets: List[str] = Field(default_factory=list)
    x_account_ref: Optional[str] = None


class Integrations(BaseModel):
    """Integration configuration."""

    enabled_adapters: EnabledAdapters = Field(default_factory=EnabledAdapters)
    routing: Routing


class Persistence(BaseModel):
    """Persistence backend pointers."""

    primary_backend: str = "persistence_api"
    last_persist_iso: Optional[str] = None


class GitHubSurface(BaseModel):
    """GitHub surface artifact pointers."""

    last_public_artifact_ref: Optional[str] = None


class Pointers(BaseModel):
    """External system pointers."""

    persistence: Persistence = Field(default_factory=Persistence)
    github_surface: GitHubSurface = Field(default_factory=GitHubSurface)


class State(BaseModel):
    """
    Complete runtime state.

    This is the root model for state/current.json.
    """

    meta: Meta
    mode: Mode
    timer: Timer
    renewal: Renewal
    security: Security
    escalation: Escalation
    actions: Actions = Field(default_factory=Actions)
    release: ReleaseConfig = Field(default_factory=ReleaseConfig)
    integrations: Integrations
    pointers: Pointers = Field(default_factory=Pointers)
