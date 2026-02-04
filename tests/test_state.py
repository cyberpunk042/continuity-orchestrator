"""
Tests for state mutation logic.

These tests verify:
- set_state mutations
- set field mutations
- clear field mutations
- Multiple rule mutations
"""

from datetime import datetime, timezone

import pytest

from src.engine.state import (
    set_nested_value,
    clear_nested_value,
    apply_rule_mutation,
    apply_rules,
)
from src.models.state import State, Meta, Mode, Timer, Renewal, Security, Escalation, Integrations, Routing
from src.policy.models import Rule


def make_state(escalation_state: str = "OK") -> State:
    """Create a minimal state for testing."""
    return State(
        meta=Meta(
            schema_version=1,
            project="test",
            state_id="TEST-001",
            updated_at_iso="2026-01-01T00:00:00Z",
            policy_version=1,
            plan_id="test",
        ),
        mode=Mode(name="renewable_countdown", armed=True),
        timer=Timer(
            deadline_iso="2026-02-05T12:00:00Z",
            grace_minutes=5,
            time_to_deadline_minutes=100,
            overdue_minutes=0,
        ),
        renewal=Renewal(
            last_renewal_iso="2026-01-01T00:00:00Z",
            renewed_this_tick=False,
        ),
        security=Security(
            failed_attempts=3,
            lockout_active=False,
        ),
        escalation=Escalation(
            state=escalation_state,
            state_entered_at_iso="2026-01-01T00:00:00Z",
        ),
        integrations=Integrations(
            routing=Routing(
                operator_email="test@example.com",
                operator_sms="+15555550000",
            ),
        ),
    )


class TestSetNestedValue:
    """Tests for nested value setting."""

    def test_set_simple_value(self):
        """Set a direct attribute."""
        state = make_state()
        set_nested_value(state, "meta.project", "new-project")
        assert state.meta.project == "new-project"

    def test_set_deep_value(self):
        """Set a deeply nested attribute."""
        state = make_state()
        set_nested_value(state, "timer.grace_minutes", 10)
        assert state.timer.grace_minutes == 10

    def test_set_boolean_value(self):
        """Set a boolean attribute."""
        state = make_state()
        set_nested_value(state, "security.lockout_active", True)
        assert state.security.lockout_active is True


class TestClearNestedValue:
    """Tests for clearing nested values."""

    def test_clear_integer_sets_zero(self):
        """Clearing an integer sets it to 0."""
        state = make_state()
        state.security.failed_attempts = 5
        clear_nested_value(state, "security.failed_attempts")
        assert state.security.failed_attempts == 0

    def test_clear_boolean_sets_false(self):
        """Clearing a boolean sets it to a falsy value."""
        state = make_state()
        state.security.lockout_active = True
        clear_nested_value(state, "security.lockout_active")
        assert not state.security.lockout_active  # Falsy (0 or False)


class TestApplyRuleMutation:
    """Tests for applying a single rule's mutations."""

    def test_set_state_changes_escalation(self):
        """set_state changes the escalation state."""
        state = make_state(escalation_state="OK")
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        
        rule = Rule(
            id="R10",
            description="Escalate to REMIND_1",
            when={},
            then={"set_state": "REMIND_1"},
        )
        
        result = apply_rule_mutation(state, rule, now)
        
        assert result["state_changed"] is True
        assert result["new_state"] == "REMIND_1"
        assert state.escalation.state == "REMIND_1"
        assert state.escalation.last_transition_rule_id == "R10"

    def test_set_state_same_state_no_change(self):
        """Setting the same state doesn't count as changed."""
        state = make_state(escalation_state="REMIND_1")
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        
        rule = Rule(
            id="R10",
            description="Already REMIND_1",
            when={},
            then={"set_state": "REMIND_1"},
        )
        
        result = apply_rule_mutation(state, rule, now)
        
        assert result["state_changed"] is False

    def test_set_field_mutation(self):
        """set mutations update fields."""
        state = make_state()
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        
        rule = Rule(
            id="R01",
            description="Activate lockout",
            when={},
            then={"set": {"security.lockout_active": True}},
        )
        
        result = apply_rule_mutation(state, rule, now)
        
        assert "security.lockout_active" in result["fields_set"]
        assert state.security.lockout_active is True

    def test_clear_field_mutation(self):
        """clear mutations reset fields."""
        state = make_state()
        state.security.failed_attempts = 5
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        
        rule = Rule(
            id="R00",
            description="Reset on renewal",
            when={},
            then={"clear": ["security.failed_attempts"]},
        )
        
        result = apply_rule_mutation(state, rule, now)
        
        assert "security.failed_attempts" in result["fields_cleared"]
        assert state.security.failed_attempts == 0


class TestApplyRules:
    """Tests for applying multiple rules."""

    def test_multiple_rules_applied_in_order(self):
        """Multiple matched rules are all applied."""
        state = make_state(escalation_state="OK")
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        
        rules = [
            Rule(id="R1", description="Set field", when={}, then={"set": {"timer.grace_minutes": 15}}),
            Rule(id="R2", description="Set state", when={}, then={"set_state": "REMIND_1"}),
        ]
        
        result = apply_rules(state, rules, now)
        
        assert result["state_changed"] is True
        assert result["new_state"] == "REMIND_1"
        assert len(result["rules_applied"]) == 2
        assert state.timer.grace_minutes == 15

    def test_last_state_change_wins(self):
        """If multiple rules change state, last one wins."""
        state = make_state(escalation_state="OK")
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        
        rules = [
            Rule(id="R1", description="To REMIND_1", when={}, then={"set_state": "REMIND_1"}),
            Rule(id="R2", description="To REMIND_2", when={}, then={"set_state": "REMIND_2"}),
        ]
        
        result = apply_rules(state, rules, now)
        
        assert result["new_state"] == "REMIND_2"
        assert state.escalation.state == "REMIND_2"
