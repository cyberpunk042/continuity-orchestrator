"""
Audit Ledger — Append-only NDJSON audit log.

Each line is one JSON object (newline-delimited JSON).
Events are never edited, only appended.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4


class AuditWriter:
    """
    Append-only NDJSON audit ledger writer.
    
    Usage:
        audit = AuditWriter(Path("audit/ledger.ndjson"))
        audit.emit("tick_start", tick_id="T-123", state_id="S-001")
    """
    
    def __init__(self, path: Path):
        """Initialize the audit writer."""
        self.path = path
        self._ensure_exists()
    
    def _ensure_exists(self) -> None:
        """Ensure the audit file and directory exist."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
    
    def emit(
        self,
        event_type: str,
        tick_id: str,
        state_id: str,
        level: str = "info",
        details: Optional[Dict[str, Any]] = None,
        escalation_state: Optional[str] = None,
        policy_version: Optional[int] = None,
        plan_id: Optional[str] = None,
    ) -> str:
        """
        Emit an audit event.
        
        Args:
            event_type: Type of event (tick_start, tick_end, rule_matched, etc.)
            tick_id: Unique identifier for this tick
            state_id: Identifier of the state record
            level: Log level (info, warning, error)
            details: Additional event details
            escalation_state: Current escalation state
            policy_version: Policy version number
            plan_id: Active plan identifier
        
        Returns:
            Generated event_id
        """
        event_id = f"E-{uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        entry: Dict[str, Any] = {
            "ts_iso": now,
            "event_id": event_id,
            "tick_id": tick_id,
            "state_id": state_id,
            "level": level,
            "type": event_type,
        }
        
        if policy_version is not None:
            entry["policy_version"] = policy_version
        if plan_id is not None:
            entry["plan_id"] = plan_id
        if escalation_state is not None:
            entry["escalation_state"] = escalation_state
        if details is not None:
            entry["details"] = details
        
        # Append to file
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        
        return event_id
    
    def emit_tick_start(
        self,
        tick_id: str,
        state_id: str,
        escalation_state: str,
        policy_version: int,
        plan_id: str,
        now_iso: str,
        deadline_iso: str,
    ) -> str:
        """Emit a tick_start event."""
        return self.emit(
            event_type="tick_start",
            tick_id=tick_id,
            state_id=state_id,
            escalation_state=escalation_state,
            policy_version=policy_version,
            plan_id=plan_id,
            details={
                "now_iso": now_iso,
                "deadline_iso": deadline_iso,
            },
        )
    
    def emit_tick_end(
        self,
        tick_id: str,
        state_id: str,
        escalation_state: str,
        policy_version: int,
        plan_id: str,
        duration_ms: int,
        actions_executed: int,
        state_changed: bool,
        matched_rules: list,
    ) -> str:
        """Emit a tick_end event."""
        return self.emit(
            event_type="tick_end",
            tick_id=tick_id,
            state_id=state_id,
            escalation_state=escalation_state,
            policy_version=policy_version,
            plan_id=plan_id,
            details={
                "duration_ms": duration_ms,
                "actions_executed": actions_executed,
                "state_changed": state_changed,
                "matched_rules": matched_rules,
            },
        )
    
    def emit_rule_matched(
        self,
        tick_id: str,
        state_id: str,
        rule_id: str,
        escalation_state: str,
        policy_version: int,
        plan_id: str,
    ) -> str:
        """Emit a rule_matched event."""
        return self.emit(
            event_type="rule_matched",
            tick_id=tick_id,
            state_id=state_id,
            escalation_state=escalation_state,
            policy_version=policy_version,
            plan_id=plan_id,
            details={"rule_id": rule_id},
        )
    
    def emit_state_transition(
        self,
        tick_id: str,
        state_id: str,
        from_state: str,
        to_state: str,
        rule_id: str,
        policy_version: int,
        plan_id: str,
    ) -> str:
        """Emit a state_transition event."""
        return self.emit(
            event_type="state_transition",
            tick_id=tick_id,
            state_id=state_id,
            policy_version=policy_version,
            plan_id=plan_id,
            details={
                "from": from_state,
                "to": to_state,
                "rule_id": rule_id,
            },
        )
