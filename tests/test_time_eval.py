"""
Tests for time evaluation logic.

These tests verify:
- Time-to-deadline calculations
- Overdue calculations
- Grace period handling
- Timezone handling
"""

from datetime import datetime, timezone, timedelta

import pytest

from src.engine.time_eval import compute_time_fields
from src.models.state import State, Meta, Mode, Timer, Renewal, Security, Escalation, Integrations, Routing


def make_state(deadline_iso: str, grace_minutes: int = 0) -> State:
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
            deadline_iso=deadline_iso,
            grace_minutes=grace_minutes,
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
            state="OK",
            state_entered_at_iso="2026-01-01T00:00:00Z",
        ),
        integrations=Integrations(
            routing=Routing(
                operator_email="test@example.com",
                operator_sms="+15555550000",
            ),
        ),
    )


class TestTimeToDeadline:
    """Tests for time_to_deadline_minutes calculation."""

    def test_future_deadline_calculates_positive_minutes(self):
        """When deadline is in the future, time_to_deadline is positive."""
        # Deadline is 2 hours from now
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        deadline = now + timedelta(hours=2)
        
        state = make_state(deadline.isoformat())
        compute_time_fields(state, now=now)
        
        assert state.timer.time_to_deadline_minutes == 120
        assert state.timer.overdue_minutes == 0

    def test_past_deadline_gives_zero_time_to_deadline(self):
        """When deadline has passed, time_to_deadline is 0."""
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        deadline = now - timedelta(hours=1)  # 1 hour ago
        
        state = make_state(deadline.isoformat())
        compute_time_fields(state, now=now)
        
        assert state.timer.time_to_deadline_minutes == 0
        assert state.timer.overdue_minutes == 60

    def test_exact_deadline_gives_zero_both(self):
        """When at exact deadline, time_to_deadline is 0, not overdue yet."""
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        
        state = make_state(now.isoformat())
        compute_time_fields(state, now=now)
        
        assert state.timer.time_to_deadline_minutes == 0
        assert state.timer.overdue_minutes == 0


class TestGracePeriod:
    """Tests for grace period handling."""

    def test_within_grace_period_not_overdue(self):
        """Within grace period, overdue_minutes stays 0."""
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        deadline = now - timedelta(minutes=5)  # 5 minutes past deadline
        
        state = make_state(deadline.isoformat(), grace_minutes=10)
        compute_time_fields(state, now=now)
        
        # 5 min past, but 10 min grace → not yet overdue
        assert state.timer.time_to_deadline_minutes == 0
        assert state.timer.overdue_minutes == 0

    def test_past_grace_period_is_overdue(self):
        """Past grace period, overdue_minutes starts counting."""
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        deadline = now - timedelta(minutes=15)  # 15 minutes past deadline
        
        state = make_state(deadline.isoformat(), grace_minutes=10)
        compute_time_fields(state, now=now)
        
        # 15 min past, 10 min grace → 5 min overdue
        assert state.timer.time_to_deadline_minutes == 0
        assert state.timer.overdue_minutes == 5

    def test_at_grace_boundary_not_overdue(self):
        """At exact grace boundary, not yet overdue."""
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        deadline = now - timedelta(minutes=10)  # Exactly at grace limit
        
        state = make_state(deadline.isoformat(), grace_minutes=10)
        compute_time_fields(state, now=now)
        
        assert state.timer.time_to_deadline_minutes == 0
        assert state.timer.overdue_minutes == 0


class TestTimezoneHandling:
    """Tests for timezone edge cases."""

    def test_deadline_without_timezone_treated_as_utc(self):
        """Deadlines without timezone info are treated as UTC."""
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        deadline_str = "2026-02-04T14:00:00"  # No timezone
        
        state = make_state(deadline_str)
        compute_time_fields(state, now=now)
        
        # Should be 2 hours = 120 minutes
        assert state.timer.time_to_deadline_minutes == 120

    def test_deadline_with_offset_handled_correctly(self):
        """Deadlines with timezone offset are converted properly."""
        now = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        # 14:00 EST = 19:00 UTC (EST is UTC-5)
        deadline_str = "2026-02-04T14:00:00-05:00"
        
        state = make_state(deadline_str)
        compute_time_fields(state, now=now)
        
        # From 12:00 UTC to 19:00 UTC = 7 hours = 420 minutes
        assert state.timer.time_to_deadline_minutes == 420

    def test_now_timestamp_is_set(self):
        """now_iso is set on the state after compute."""
        now = datetime(2026, 2, 4, 12, 30, 45, tzinfo=timezone.utc)
        
        state = make_state("2026-02-05T12:00:00Z")
        compute_time_fields(state, now=now)
        
        assert state.timer.now_iso is not None
        assert "2026-02-04" in state.timer.now_iso
