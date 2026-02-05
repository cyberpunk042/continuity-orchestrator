#!/usr/bin/env python3
"""Docker state initializer - creates a fresh state file."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

def create_initial_state():
    """Create initial state file for Docker test mode."""
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(hours=48)
    
    state = {
        "meta": {
            "schema_version": 1,
            "project": "continuity-test",
            "state_id": f"S-INIT-{now.strftime('%Y%m%d')}",
            "updated_at_iso": now.isoformat(),
            "policy_version": 1,
            "plan_id": "default"
        },
        "mode": {
            "name": "renewable_countdown",
            "armed": True
        },
        "timer": {
            "deadline_iso": deadline.isoformat(),
            "grace_minutes": 0,
            "now_iso": now.isoformat(),
            "time_to_deadline_minutes": 2880,
            "overdue_minutes": 0
        },
        "renewal": {
            "last_renewal_iso": now.isoformat(),
            "renewed_this_tick": False,
            "renewal_count": 0
        },
        "security": {
            "failed_attempts": 0,
            "lockout_active": False,
            "lockout_until_iso": None,
            "max_failed_attempts": 3,
            "lockout_minutes": 60
        },
        "escalation": {
            "state": "OK",
            "state_entered_at_iso": now.isoformat(),
            "last_transition_rule_id": None
        },
        "actions": {
            "executed": {},
            "last_tick_actions": []
        },
        "integrations": {
            "enabled_adapters": {
                "email": True,
                "sms": False,
                "x": False,
                "reddit": False,
                "webhook": True,
                "github_surface": False,
                "article_publish": False,
                "persistence_api": False
            },
            "routing": {
                "github_repository": "test/repo",
                "operator_email": "test@example.com",
                "operator_sms": None,
                "custodian_emails": [],
                "observer_webhooks": [],
                "reddit_targets": [],
                "x_account_ref": None
            }
        },
        "pointers": {
            "persistence": {
                "primary_backend": "file",
                "last_persist_iso": None
            },
            "github_surface": {
                "last_public_artifact_ref": None
            }
        }
    }
    
    return state


if __name__ == "__main__":
    import sys
    
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/data/state/current.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    state = create_initial_state()
    
    with open(output_path, "w") as f:
        json.dump(state, f, indent=4)
    
    print(f"✅ State initialized at {output_path}")
