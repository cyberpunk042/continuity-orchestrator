"""
Policy Models — Pydantic schemas for policy configuration.

Policy files define:
- states.yaml: Escalation state machine
- rules.yaml: Transition conditions
- plans/*.yaml: Actions per stage
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# --- States Policy ---


class StateFlags(BaseModel):
    """Flags controlling what's allowed in a state."""

    outward_actions_allowed: bool = False
    reminders_allowed: bool = False


class StateDefinition(BaseModel):
    """Definition of an escalation state."""

    name: str
    order: int
    description: Optional[str] = None
    flags: StateFlags = Field(default_factory=StateFlags)


class ResetBehavior(BaseModel):
    """Behavior on reset conditions."""

    target_state: str
    description: str


class StatesPolicy(BaseModel):
    """The states.yaml schema."""

    version: int = 1
    notes: List[str] = Field(default_factory=list)
    states: List[StateDefinition]
    terminal_states: List[str] = Field(default_factory=list)
    reset_behavior: Dict[str, ResetBehavior] = Field(default_factory=dict)
    stage_progression_defaults: List[Dict[str, str]] = Field(default_factory=list)

    def get_state_order(self, state_name: str) -> int:
        """Get the order number for a state."""
        for state in self.states:
            if state.name == state_name:
                return state.order
        return -1


# --- Rules Policy ---


class Rule(BaseModel):
    """A single policy rule."""

    id: str
    description: str
    when: Dict[str, Any]  # Conditions to evaluate
    then: Dict[str, Any]  # Mutations when matched
    stop: bool = False
    enabled: bool = True  # Disabled rules are skipped during evaluation


class RulesPolicy(BaseModel):
    """The rules.yaml schema."""

    version: int = 1
    notes: Any = None  # Flexible: can be list of strings or other
    inputs: Dict[str, List[str]] = Field(default_factory=dict)
    constants: Dict[str, int] = Field(default_factory=dict)
    rules: List[Rule]


# --- Plan Policy ---


class ActionConstraints(BaseModel):
    """Constraints on action execution."""

    no_links: bool = False
    no_entrypoint_reference: bool = False
    limited_scope: bool = False
    max_length: Optional[int] = None


class ActionDefinition(BaseModel):
    """An action to execute at a stage."""

    id: str
    adapter: str
    channel: str
    template: Optional[str] = None
    payload: Optional[str] = None
    artifact: Optional[Dict[str, Any]] = None
    constraints: Optional[ActionConstraints] = None


class StageActions(BaseModel):
    """Actions for a single stage."""

    description: str
    actions: List[ActionDefinition] = Field(default_factory=list)


class RetryPolicy(BaseModel):
    """Retry configuration for failures."""

    max_attempts: int = 3
    backoff_seconds: int = 60


class OnExhausted(BaseModel):
    """Behavior when retries are exhausted."""

    record_failure: bool = True
    continue_execution: bool = True


class FailureHandling(BaseModel):
    """How to handle adapter failures."""

    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    on_exhausted: OnExhausted = Field(default_factory=OnExhausted)


class ReceiptsConfig(BaseModel):
    """Receipt recording configuration."""

    record: bool = True
    fields: List[str] = Field(default_factory=list)


class Plan(BaseModel):
    """The plans/*.yaml schema."""

    version: int = 1
    notes: List[str] = Field(default_factory=list)
    plan_id: Optional[str] = None
    name: Optional[str] = None  # Alias for plan_id
    description: Optional[str] = None
    stages: Dict[str, StageActions]
    receipts: ReceiptsConfig = Field(default_factory=ReceiptsConfig)
    failure_handling: FailureHandling = Field(default_factory=FailureHandling)

    def get_actions_for_stage(self, stage: str) -> List[ActionDefinition]:
        """Get actions for a given stage."""
        if stage in self.stages:
            return self.stages[stage].actions
        return []


# --- Combined Policy ---


class Policy(BaseModel):
    """Combined policy from all files."""

    states: StatesPolicy
    rules: RulesPolicy
    plan: Plan
