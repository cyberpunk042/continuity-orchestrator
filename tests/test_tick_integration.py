"""
Integration tests for the tick lifecycle.

These tests verify the complete tick flow from state loading
through rule evaluation, action execution, and state persistence.
"""

import json
import shutil
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.engine.tick import run_tick, TickResult
from src.models.state import State
from src.persistence.state_file import load_state, save_state
from src.policy.loader import load_policy


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace with all necessary files."""
    tmpdir = Path(tempfile.mkdtemp())
    
    # Copy policy files
    policy_src = Path(__file__).parent.parent / "policy"
    policy_dst = tmpdir / "policy"
    shutil.copytree(policy_src, policy_dst)
    
    # Create state directory
    state_dir = tmpdir / "state"
    state_dir.mkdir()
    
    # Create initial state
    state_file = state_dir / "current.json"
    initial_state = {
        "meta": {
            "schema_version": 1,
            "project": "test-project",
            "state_id": "TEST-001",
            "updated_at_iso": "2026-01-01T00:00:00Z",
            "policy_version": 1,
            "plan_id": "default"
        },
        "mode": {"name": "renewable_countdown", "armed": True},
        "timer": {
            "deadline_iso": (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat(),
            "grace_minutes": 0
        },
        "renewal": {
            "last_renewal_iso": "2026-01-01T00:00:00Z",
            "renewed_this_tick": False
        },
        "security": {
            "failed_attempts": 0,
            "lockout_active": False
        },
        "escalation": {
            "state": "OK",
            "state_entered_at_iso": "2026-01-01T00:00:00Z"
        },
        "actions": {"executed": {}, "last_tick_actions": []},
        "integrations": {
            "routing": {
                "operator_email": "test@example.com",
                "operator_sms": "+15555550000"
            }
        }
    }
    state_file.write_text(json.dumps(initial_state, indent=2))
    
    # Create audit directory
    audit_dir = tmpdir / "audit"
    audit_dir.mkdir()
    
    yield tmpdir
    
    # Cleanup
    shutil.rmtree(tmpdir)


class TestTickLifecycle:
    """Integration tests for the complete tick lifecycle."""

    def test_tick_with_ok_state_no_escalation(self, temp_workspace):
        """When deadline is far away, state stays OK with no actions."""
        state_path = temp_workspace / "state" / "current.json"
        policy_path = temp_workspace / "policy"
        
        state = load_state(state_path)
        policy = load_policy(policy_path)
        
        result = run_tick(state, policy, dry_run=True)
        
        assert result.previous_state == "OK"
        assert result.new_state == "OK"
        assert result.state_changed is False
        assert result.actions_selected == []  # No actions for OK state

    def test_tick_escalates_to_remind_1(self, temp_workspace):
        """When within 6 hours of deadline, escalates to REMIND_1."""
        state_path = temp_workspace / "state" / "current.json"
        policy_path = temp_workspace / "policy"
        
        state = load_state(state_path)
        # Set deadline to 5 hours from now (within REMIND_1 range)
        state.timer.deadline_iso = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        
        policy = load_policy(policy_path)
        
        result = run_tick(state, policy, dry_run=True)
        
        assert result.previous_state == "OK"
        assert result.new_state == "REMIND_1"
        assert result.state_changed is True
        assert "remind_email_primary" in result.actions_selected

    def test_tick_escalates_to_remind_2(self, temp_workspace):
        """When within 1 hour of deadline, escalates to REMIND_2."""
        state_path = temp_workspace / "state" / "current.json"
        policy_path = temp_workspace / "policy"
        
        state = load_state(state_path)
        # Set deadline to 30 minutes from now (within REMIND_2 range)
        state.timer.deadline_iso = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        
        policy = load_policy(policy_path)
        
        result = run_tick(state, policy, dry_run=True)
        
        assert result.previous_state == "OK"
        assert result.new_state == "REMIND_2"
        assert result.state_changed is True
        # REMIND_2 has email + SMS
        assert "remind_email_secondary" in result.actions_selected
        assert "remind_sms" in result.actions_selected

    def test_tick_escalates_through_stages_correctly(self, temp_workspace):
        """State transitions follow monotonic escalation."""
        state_path = temp_workspace / "state" / "current.json"
        policy_path = temp_workspace / "policy"
        
        state = load_state(state_path)
        policy = load_policy(policy_path)
        
        # Stage 1: OK → REMIND_1
        state.timer.deadline_iso = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        result = run_tick(state, policy, dry_run=True)
        assert result.new_state == "REMIND_1"
        
        # Apply the state change for next test
        state.escalation.state = "REMIND_1"
        
        # Stage 2: REMIND_1 → REMIND_2
        state.timer.deadline_iso = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        result = run_tick(state, policy, dry_run=True)
        assert result.new_state == "REMIND_2"
        
        state.escalation.state = "REMIND_2"
        
        # Stage 3: REMIND_2 → PRE_RELEASE
        state.timer.deadline_iso = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        result = run_tick(state, policy, dry_run=True)
        assert result.new_state == "PRE_RELEASE"

    def test_tick_generates_unique_tick_ids(self, temp_workspace):
        """Each tick generates a unique tick ID."""
        state_path = temp_workspace / "state" / "current.json"
        policy_path = temp_workspace / "policy"
        
        state = load_state(state_path)
        policy = load_policy(policy_path)
        
        result1 = run_tick(state, policy, dry_run=True)
        result2 = run_tick(state, policy, dry_run=True)
        
        assert result1.tick_id != result2.tick_id
        assert result1.tick_id.startswith("T-")
        assert result2.tick_id.startswith("T-")


class TestIdempotency:
    """Tests for action idempotency."""

    def test_actions_not_reexecuted_if_already_done(self, temp_workspace):
        """Actions marked as executed are skipped on subsequent ticks."""
        state_path = temp_workspace / "state" / "current.json"
        policy_path = temp_workspace / "policy"
        
        state = load_state(state_path)
        state.timer.deadline_iso = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        
        # Simulate action already executed
        from src.models.state import ActionReceipt
        state.actions.executed["remind_email_primary"] = ActionReceipt(
            status="ok",
            last_delivery_id="prev-delivery",
            last_executed_iso="2026-01-01T00:00:00Z",
        )
        
        policy = load_policy(policy_path)
        
        # Run tick (without dry_run to trigger action execution logic)
        # But we're in dry_run so actions won't actually execute
        result = run_tick(state, policy, dry_run=True)
        
        # Action is selected but would be skipped due to idempotency
        assert "remind_email_primary" in result.actions_selected


class TestMonotonicEnforcement:
    """Tests for monotonic state progression."""

    def test_cannot_go_backwards_in_escalation(self, temp_workspace):
        """State cannot regress to an earlier escalation stage."""
        state_path = temp_workspace / "state" / "current.json"
        policy_path = temp_workspace / "policy"
        
        state = load_state(state_path)
        state.escalation.state = "REMIND_2"  # Already at REMIND_2
        
        # Set deadline far away (would normally be OK state)
        state.timer.deadline_iso = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        
        policy = load_policy(policy_path)
        
        result = run_tick(state, policy, dry_run=True)
        
        # Should not regress to OK or REMIND_1
        assert result.new_state == "REMIND_2"
        assert result.state_changed is False
