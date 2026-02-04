"""
Tests for rule evaluation logic.

These tests verify:
- Condition operators (lte, gte, lt, gt)
- State matching (state_is, state_in)
- Path aliasing (time. → timer.)
- Constant resolution
- Rule matching (AND logic, stop behavior)
"""

from datetime import datetime, timezone

import pytest

from src.engine.rules import (
    get_nested_value,
    resolve_value,
    evaluate_condition,
    evaluate_rule,
    evaluate_rules,
)
from src.models.state import State, Meta, Mode, Timer, Renewal, Security, Escalation, Integrations, Routing
from src.policy.models import Rule, RulesPolicy


def make_state(
    escalation_state: str = "OK",
    time_to_deadline: int = 100,
    overdue: int = 0,
) -> State:
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
            grace_minutes=0,
            now_iso="2026-02-04T12:00:00Z",
            time_to_deadline_minutes=time_to_deadline,
            overdue_minutes=overdue,
        ),
        renewal=Renewal(
            last_renewal_iso="2026-01-01T00:00:00Z",
            renewed_this_tick=False,
        ),
        security=Security(
            failed_attempts=0,
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


class TestGetNestedValue:
    """Tests for nested value access."""

    def test_simple_path(self):
        """Access a top-level attribute."""
        state = make_state()
        value = get_nested_value(state, "meta.project")
        assert value == "test"

    def test_deep_path(self):
        """Access a deeply nested attribute."""
        state = make_state()
        value = get_nested_value(state, "integrations.routing.operator_email")
        assert value == "test@example.com"

    def test_path_aliasing_time_to_timer(self):
        """The 'time.' prefix is aliased to 'timer.'."""
        state = make_state(time_to_deadline=300)
        value = get_nested_value(state, "time.time_to_deadline_minutes")
        assert value == 300

    def test_nonexistent_path_returns_none(self):
        """Missing paths return None, not raise."""
        state = make_state()
        value = get_nested_value(state, "nonexistent.path")
        assert value is None


class TestResolveValue:
    """Tests for constant resolution."""

    def test_constant_reference_resolved(self):
        """'constants.name' is resolved from dict."""
        constants = {"threshold": 360}
        value = resolve_value("constants.threshold", constants)
        assert value == 360

    def test_non_constant_unchanged(self):
        """Regular values pass through unchanged."""
        constants = {}
        value = resolve_value(100, constants)
        assert value == 100

    def test_missing_constant_returns_original(self):
        """Missing constant reference returns the string."""
        constants = {}
        value = resolve_value("constants.missing", constants)
        assert value == "constants.missing"


class TestEvaluateCondition:
    """Tests for individual condition evaluation."""

    def test_state_is_matches(self):
        """state_is matches exact state."""
        state = make_state(escalation_state="REMIND_1")
        assert evaluate_condition("state_is", "REMIND_1", state, {}) is True
        assert evaluate_condition("state_is", "OK", state, {}) is False

    def test_state_in_matches_list(self):
        """state_in matches if state is in list."""
        state = make_state(escalation_state="REMIND_2")
        assert evaluate_condition("state_in", ["REMIND_1", "REMIND_2"], state, {}) is True
        assert evaluate_condition("state_in", ["OK", "REMIND_1"], state, {}) is False

    def test_lte_operator(self):
        """_lte matches when value <= expected."""
        state = make_state(time_to_deadline=100)
        assert evaluate_condition("timer.time_to_deadline_minutes_lte", 100, state, {}) is True
        assert evaluate_condition("timer.time_to_deadline_minutes_lte", 99, state, {}) is False

    def test_gte_operator(self):
        """_gte matches when value >= expected."""
        state = make_state(time_to_deadline=100)
        assert evaluate_condition("timer.time_to_deadline_minutes_gte", 100, state, {}) is True
        assert evaluate_condition("timer.time_to_deadline_minutes_gte", 101, state, {}) is False

    def test_lt_operator(self):
        """_lt matches when value < expected."""
        state = make_state(time_to_deadline=99)
        assert evaluate_condition("timer.time_to_deadline_minutes_lt", 100, state, {}) is True
        assert evaluate_condition("timer.time_to_deadline_minutes_lt", 99, state, {}) is False

    def test_gt_operator(self):
        """_gt matches when value > expected."""
        state = make_state(time_to_deadline=101)
        assert evaluate_condition("timer.time_to_deadline_minutes_gt", 100, state, {}) is True
        assert evaluate_condition("timer.time_to_deadline_minutes_gt", 101, state, {}) is False

    def test_equality_without_operator(self):
        """No operator suffix means exact equality."""
        state = make_state(escalation_state="OK")
        assert evaluate_condition("escalation.state", "OK", state, {}) is True
        assert evaluate_condition("escalation.state", "REMIND_1", state, {}) is False

    def test_path_alias_in_condition(self):
        """time. path is aliased to timer. for conditions."""
        state = make_state(time_to_deadline=50)
        assert evaluate_condition("time.time_to_deadline_minutes_lte", 60, state, {}) is True


class TestEvaluateRule:
    """Tests for full rule evaluation."""

    def test_all_conditions_must_match(self):
        """Rule matches only if ALL conditions match (AND logic)."""
        state = make_state(escalation_state="OK", time_to_deadline=300)
        
        rule = Rule(
            id="test",
            description="Test rule",
            when={
                "state_is": "OK",
                "time.time_to_deadline_minutes_lte": 360,
            },
            then={"set_state": "REMIND_1"},
        )
        
        # Both conditions match
        assert evaluate_rule(rule, state, {}) is True
        
        # One condition fails
        state2 = make_state(escalation_state="REMIND_1", time_to_deadline=300)
        assert evaluate_rule(rule, state2, {}) is False

    def test_constant_in_condition(self):
        """Constants are resolved during evaluation."""
        state = make_state(time_to_deadline=300)
        constants = {"threshold": 360}
        
        rule = Rule(
            id="test",
            description="Test rule",
            when={"time.time_to_deadline_minutes_lte": "constants.threshold"},
            then={},
        )
        
        assert evaluate_rule(rule, state, constants) is True


class TestEvaluateRules:
    """Tests for multi-rule evaluation."""

    def test_rules_evaluated_in_order(self):
        """Rules are evaluated top to bottom."""
        state = make_state(escalation_state="OK", time_to_deadline=300)
        
        rules_policy = RulesPolicy(
            rules=[
                Rule(id="R1", description="First", when={"state_is": "OK"}, then={}),
                Rule(id="R2", description="Second", when={"state_is": "OK"}, then={}),
            ],
            constants={},
        )
        
        matched = evaluate_rules(state, rules_policy)
        assert [r.id for r in matched] == ["R1", "R2"]

    def test_stop_halts_evaluation(self):
        """Rule with stop=True prevents further evaluation."""
        state = make_state(escalation_state="OK")
        
        rules_policy = RulesPolicy(
            rules=[
                Rule(id="R1", description="First", when={"state_is": "OK"}, then={}, stop=True),
                Rule(id="R2", description="Second", when={"state_is": "OK"}, then={}),
            ],
            constants={},
        )
        
        matched = evaluate_rules(state, rules_policy)
        assert [r.id for r in matched] == ["R1"]  # R2 not evaluated

    def test_non_matching_rules_skipped(self):
        """Rules that don't match are not included."""
        state = make_state(escalation_state="OK")
        
        rules_policy = RulesPolicy(
            rules=[
                Rule(id="R1", description="Matches", when={"state_is": "OK"}, then={}),
                Rule(id="R2", description="No match", when={"state_is": "REMIND_1"}, then={}),
                Rule(id="R3", description="Matches", when={"state_is": "OK"}, then={}),
            ],
            constants={},
        )
        
        matched = evaluate_rules(state, rules_policy)
        assert [r.id for r in matched] == ["R1", "R3"]
