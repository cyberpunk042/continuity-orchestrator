"""
Time Evaluation — Compute deadline and overdue values.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from dateutil import parser as date_parser

from ..models.state import State


def compute_time_fields(state: State, now: Optional[datetime] = None) -> None:
    """
    Compute time-derived fields on the state.
    
    Mutates state.timer in place:
    - now_iso: Current timestamp
    - time_to_deadline_minutes: Minutes until deadline (0 if overdue)
    - overdue_minutes: Minutes past deadline (0 if not overdue)
    
    Args:
        state: State object to update
        now: Override timestamp (optional, defaults to UTC now)
    """
    if now is None:
        now = datetime.now(timezone.utc)
    
    # Ensure now has timezone
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    
    # Set the tick timestamp
    state.timer.now_iso = now.isoformat().replace("+00:00", "Z")
    
    # Parse deadline
    deadline = date_parser.isoparse(state.timer.deadline_iso)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    
    # Calculate delta in minutes
    delta = deadline - now
    delta_minutes = delta.total_seconds() / 60
    
    # Apply grace period
    grace = state.timer.grace_minutes or 0
    
    if delta_minutes >= 0:
        # Before deadline
        state.timer.time_to_deadline_minutes = int(delta_minutes)
        state.timer.overdue_minutes = 0
    elif delta_minutes >= -grace:
        # In grace period — not yet overdue
        state.timer.time_to_deadline_minutes = 0
        state.timer.overdue_minutes = 0
    else:
        # Overdue (past grace period)
        state.timer.time_to_deadline_minutes = 0
        # Overdue = time past deadline minus grace period
        overdue_raw = abs(delta_minutes) - grace
        state.timer.overdue_minutes = int(max(0, overdue_raw))
