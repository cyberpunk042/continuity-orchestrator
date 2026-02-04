"""
Tests for policy loading and validation.

These tests verify:
- YAML parsing and validation
- Edge cases in policy files
- Error handling for malformed policies
"""

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from src.policy.loader import load_policy, load_yaml
from src.policy.models import Policy, StatesPolicy, RulesPolicy, Plan


class TestLoadYaml:
    """Tests for YAML loading utility."""

    def test_loads_valid_yaml(self, tmp_path):
        """Valid YAML file is parsed correctly."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\nnested:\n  foo: bar")
        
        result = load_yaml(yaml_file)
        
        assert result["key"] == "value"
        assert result["nested"]["foo"] == "bar"

    def test_handles_empty_file(self, tmp_path):
        """Empty YAML file returns empty dict."""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")
        
        result = load_yaml(yaml_file)
        
        assert result == {} or result is None

    def test_handles_comments_only(self, tmp_path):
        """File with only comments returns empty dict."""
        yaml_file = tmp_path / "comments.yaml"
        yaml_file.write_text("# Just a comment\n# Another comment")
        
        result = load_yaml(yaml_file)
        
        assert result is None or result == {}


class TestLoadStatesPolicy:
    """Tests for states.yaml loading."""

    def test_loads_states_with_all_fields(self, tmp_path):
        """States with all fields are parsed correctly."""
        states_yaml = tmp_path / "states.yaml"
        states_yaml.write_text("""
states:
  - name: OK
    order: 0
    description: Normal operation
    flags:
      outward_actions_allowed: false
      reminders_allowed: true
  - name: REMIND_1
    order: 1
    description: First reminder
""")
        
        data = load_yaml(states_yaml)
        policy = StatesPolicy(**data)
        
        assert len(policy.states) == 2
        assert policy.states[0].name == "OK"
        assert policy.states[0].order == 0
        assert policy.states[0].flags.outward_actions_allowed is False

    def test_states_with_missing_optional_fields(self, tmp_path):
        """States with missing optional fields use defaults."""
        states_yaml = tmp_path / "states.yaml"
        states_yaml.write_text("""
states:
  - name: OK
    order: 0
  - name: FULL
    order: 5
""")
        
        data = load_yaml(states_yaml)
        policy = StatesPolicy(**data)
        
        assert policy.states[0].description is None
        assert policy.states[0].flags.outward_actions_allowed is False  # Default


class TestLoadRulesPolicy:
    """Tests for rules.yaml loading."""

    def test_loads_rules_with_conditions(self, tmp_path):
        """Rules with conditions are parsed correctly."""
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text("""
version: 1
constants:
  threshold: 360
rules:
  - id: R01
    description: Test rule
    when:
      state_is: OK
      time.time_to_deadline_minutes_lte: 360
    then:
      set_state: REMIND_1
    stop: true
""")
        
        data = load_yaml(rules_yaml)
        policy = RulesPolicy(**data)
        
        assert len(policy.rules) == 1
        assert policy.rules[0].id == "R01"
        assert policy.rules[0].when["state_is"] == "OK"
        assert policy.rules[0].then["set_state"] == "REMIND_1"
        assert policy.rules[0].stop is True
        assert policy.constants["threshold"] == 360

    def test_rules_with_complex_mutations(self, tmp_path):
        """Rules with set and clear mutations are parsed."""
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text("""
version: 1
rules:
  - id: R01
    description: Test mutations
    when:
      always: true
    then:
      set:
        security.lockout_active: true
        timer.grace_minutes: 10
      clear:
        - security.failed_attempts
""")
        
        data = load_yaml(rules_yaml)
        policy = RulesPolicy(**data)
        
        rule = policy.rules[0]
        assert rule.then["set"]["security.lockout_active"] is True
        assert rule.then["clear"] == ["security.failed_attempts"]

    def test_rules_with_notes_as_list(self, tmp_path):
        """Notes field accepts list format."""
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text("""
version: 1
notes:
  - First note
  - Second note
rules: []
""")
        
        data = load_yaml(rules_yaml)
        policy = RulesPolicy(**data)
        
        assert len(policy.notes) == 2


class TestLoadPlan:
    """Tests for plans/*.yaml loading."""

    def test_loads_plan_with_stages(self, tmp_path):
        """Plan with multiple stages is parsed."""
        plan_yaml = tmp_path / "default.yaml"
        plan_yaml.write_text("""
name: default
version: 1
stages:
  REMIND_1:
    description: First reminder
    actions:
      - id: email_primary
        adapter: email
        channel: operator
        template: reminder
  REMIND_2:
    description: Second reminder
    actions:
      - id: email_secondary
        adapter: email
        channel: operator
      - id: sms
        adapter: sms
        channel: operator
""")
        
        data = load_yaml(plan_yaml)
        plan = Plan(**data)
        
        assert plan.name == "default"
        assert len(plan.stages) == 2
        assert len(plan.stages["REMIND_1"].actions) == 1
        assert len(plan.stages["REMIND_2"].actions) == 2

    def test_plan_get_actions_for_stage(self, tmp_path):
        """get_actions_for_stage returns correct actions."""
        plan_yaml = tmp_path / "default.yaml"
        plan_yaml.write_text("""
name: default
version: 1
stages:
  REMIND_1:
    description: First reminder
    actions:
      - id: action1
        adapter: email
        channel: operator
  REMIND_2:
    description: Second reminder
    actions:
      - id: action2
        adapter: sms
        channel: operator
""")
        
        data = load_yaml(plan_yaml)
        plan = Plan(**data)
        
        remind1_actions = plan.get_actions_for_stage("REMIND_1")
        assert len(remind1_actions) == 1
        assert remind1_actions[0].id == "action1"
        
        remind2_actions = plan.get_actions_for_stage("REMIND_2")
        assert len(remind2_actions) == 1
        assert remind2_actions[0].id == "action2"
        
        # Unknown stage returns empty list
        unknown_actions = plan.get_actions_for_stage("NONEXISTENT")
        assert unknown_actions == []


class TestLoadFullPolicy:
    """Integration tests for loading complete policy."""

    def test_loads_production_policy(self):
        """The actual production policy loads correctly."""
        policy_path = Path(__file__).parent.parent / "policy"
        
        if not policy_path.exists():
            pytest.skip("Production policy not found")
        
        policy = load_policy(policy_path)
        
        # Verify states
        assert len(policy.states.states) > 0
        state_names = [s.name for s in policy.states.states]
        assert "OK" in state_names
        assert "FULL" in state_names
        
        # Verify rules
        assert len(policy.rules.rules) > 0
        
        # Verify plan
        assert policy.plan is not None
        assert policy.plan.plan_id == "default" or policy.plan.name == "default"

    def test_state_ordering(self):
        """States are ordered correctly by order field."""
        policy_path = Path(__file__).parent.parent / "policy"
        
        if not policy_path.exists():
            pytest.skip("Production policy not found")
        
        policy = load_policy(policy_path)
        
        # Get state order
        order = policy.states.get_state_order("REMIND_2")
        
        # REMIND_2 should be after REMIND_1
        assert order > policy.states.get_state_order("REMIND_1")
        assert order < policy.states.get_state_order("FULL")
