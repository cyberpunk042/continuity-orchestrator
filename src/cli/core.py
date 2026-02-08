"""
CLI core commands — state lifecycle operations (reset, renew, trigger-release).

Usage:
    python -m src.main reset [--full] [--hours 48] [--yes]
    python -m src.main renew [--hours 48]
    python -m src.main trigger-release [--stage FULL] [--delay 0]
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import click


@click.command()
@click.option("--state-file", default="state/current.json")
@click.option("--full", is_flag=True, help="Full factory reset (new state + clear audit)")
@click.option("--backup/--no-backup", default=True, help="Backup existing state before reset")
@click.option("--hours", default=48, type=int, help="Initial deadline hours for full reset")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def reset(
    ctx: click.Context,
    state_file: str,
    full: bool,
    backup: bool,
    hours: int,
    yes: bool,
) -> None:
    """Reset state to OK or perform full factory reset.

    Without --full: Just resets escalation state to OK.
    With --full: Creates fresh state and clears audit log.
    """
    import json
    import shutil

    from ..persistence.state_file import load_state, save_state

    root = ctx.obj["root"]
    state_path = root / state_file
    audit_path = root / "audit" / "ledger.ndjson"
    backup_dir = root / "backups"

    if full and not yes:
        click.secho("⚠️  FULL RESET will:", fg="yellow", bold=True)
        click.echo("  - Create fresh state with new deadline")
        click.echo("  - Clear the audit log")
        if backup:
            click.echo("  - Backup existing files first")
        if not click.confirm("Continue?"):
            click.echo("Cancelled.")
            return

    now = datetime.now(timezone.utc)

    # Backup existing state if requested
    if backup and state_path.exists():
        backup_dir.mkdir(exist_ok=True)
        timestamp = now.strftime("%Y%m%dT%H%M%S")

        # Backup state
        backup_state = backup_dir / f"state_{timestamp}.json"
        shutil.copy(state_path, backup_state)
        click.echo(f"  Backed up state to: {backup_state}")

        # Backup audit log
        if full and audit_path.exists():
            backup_audit = backup_dir / f"audit_{timestamp}.ndjson"
            shutil.copy(audit_path, backup_audit)
            click.echo(f"  Backed up audit to: {backup_audit}")

    if full:
        # Full factory reset - create new state
        from ..models.state import (
            State, Meta, Mode, Timer, Renewal, Security,
            Escalation, Actions, ReleaseConfig, Integrations, EnabledAdapters,
            Routing, Pointers
        )

        # Read operator email from env or existing state
        operator_email = os.environ.get("OPERATOR_EMAIL", "operator@example.com")
        project_name = os.environ.get("PROJECT_NAME", "my-project")

        new_deadline = now + timedelta(hours=hours)

        new_state = State(
            meta=Meta(
                schema_version=1,
                project=project_name,
                state_id=f"S-INIT-{now.strftime('%Y%m%d')}",
                updated_at_iso=now.isoformat(),
                policy_version=1,
                plan_id="default",
            ),
            mode=Mode(name="renewable_countdown", armed=True),
            timer=Timer(
                deadline_iso=new_deadline.isoformat(),
                grace_minutes=0,
                now_iso=now.isoformat(),
                time_to_deadline_minutes=hours * 60,
                overdue_minutes=0,
            ),
            renewal=Renewal(
                last_renewal_iso=now.isoformat(),
                renewed_this_tick=False,
                renewal_count=0,
            ),
            security=Security(),
            escalation=Escalation(
                state="OK",
                state_entered_at_iso=now.isoformat(),
            ),
            actions=Actions(),
            release=ReleaseConfig(),
            integrations=Integrations(
                enabled_adapters=EnabledAdapters(),
                routing=Routing(operator_email=operator_email),
            ),
            pointers=Pointers(),
        )

        save_state(new_state, state_path)

        # Clear audit log (write init entry)
        audit_path.parent.mkdir(exist_ok=True)
        init_entry = {
            "event_type": "factory_reset",
            "timestamp": now.isoformat(),
            "tick_id": f"RESET-{now.strftime('%Y%m%dT%H%M%S')}",
            "new_deadline": new_deadline.isoformat(),
            "hours": hours,
        }
        with open(audit_path, "w") as f:
            f.write(json.dumps(init_entry) + "\n")

        click.secho("\n✅ Full factory reset complete", fg="green", bold=True)
        click.echo(f"  Project: {project_name}")
        click.echo(f"  Deadline: {new_deadline.isoformat()}")
        click.echo(f"  ({hours} hours from now)")
    else:
        # Simple reset - just reset escalation state
        state = load_state(state_path)

        old_state = state.escalation.state
        state.escalation.state = "OK"
        state.escalation.state_entered_at_iso = now.isoformat()
        state.escalation.last_transition_rule_id = "MANUAL_RESET"
        state.actions.executed = {}
        state.actions.last_tick_actions = []
        state.renewal.renewed_this_tick = False
        state.release.triggered = False
        state.release.client_token = None

        state.meta.updated_at_iso = now.isoformat()

        save_state(state, state_path)

        # Append to audit log
        audit_entry = {
            "event_type": "manual_reset",
            "timestamp": now.isoformat(),
            "tick_id": f"M-{now.strftime('%Y%m%dT%H%M%S')}-RESET",
            "previous_state": old_state,
            "new_state": "OK",
            "trigger": "MANUAL_RESET",
        }

        import json as _json
        with open(audit_path, "a") as f:
            f.write(_json.dumps(audit_entry) + "\n")

        click.secho("✅ State reset to OK", fg="green")
        click.echo(f"  Previous state: {old_state}")


@click.command("renew")
@click.option(
    "--hours",
    "-h",
    default=48,
    type=int,
    help="Hours to extend the deadline",
)
@click.option(
    "--state-file",
    default="state/current.json",
    help="Path to state file",
)
@click.pass_context
def renew(ctx: click.Context, hours: int, state_file: str) -> None:
    """Renew the deadline and reset state to OK."""
    import json

    from ..persistence.state_file import load_state, save_state

    root = ctx.obj["root"]
    state_path = root / state_file

    state = load_state(state_path)
    now = datetime.now(timezone.utc)

    # Calculate new deadline
    new_deadline = now + timedelta(hours=hours)
    old_state = state.escalation.state
    old_deadline = state.timer.deadline_iso

    # Update state
    state.timer.deadline_iso = new_deadline.isoformat()
    state.timer.now_iso = now.isoformat()
    state.timer.time_to_deadline_minutes = hours * 60
    state.timer.overdue_minutes = 0

    state.escalation.state = "OK"
    state.escalation.state_entered_at_iso = now.isoformat()
    state.escalation.last_transition_rule_id = "MANUAL_RENEWAL"

    state.renewal.last_renewal_iso = now.isoformat()
    state.renewal.renewed_this_tick = True
    state.renewal.renewal_count = (state.renewal.renewal_count or 0) + 1

    # Clear executed actions (fresh start)
    state.actions.executed = {}
    state.actions.last_tick_actions = []

    # Clear release trigger (renewal cancels any pending release)
    state.release.triggered = False
    state.release.trigger_time_iso = None
    state.release.execute_after_iso = None
    state.release.client_token = None

    state.meta.updated_at_iso = now.isoformat()

    save_state(state, state_path)

    # Append to audit log
    audit_path = root / "audit" / "ledger.ndjson"
    audit_entry = {
        "event_type": "renewal",
        "timestamp": now.isoformat(),
        "tick_id": f"R-{now.strftime('%Y%m%dT%H%M%S')}-RENEW",
        "previous_state": old_state,
        "new_state": "OK",
        "old_deadline": old_deadline,
        "new_deadline": new_deadline.isoformat(),
        "extended_hours": hours,
        "renewal_count": state.renewal.renewal_count,
    }

    with open(audit_path, "a") as f:
        f.write(json.dumps(audit_entry) + "\n")

    click.secho(f"✅ Renewal successful", fg="green")
    click.echo(f"  Previous state: {old_state}")
    click.echo(f"  New state: OK")
    click.echo(f"  Extended by: {hours} hours")
    click.echo(f"  New deadline: {new_deadline.isoformat()}")
    click.echo(f"  Renewal count: {state.renewal.renewal_count}")


@click.command("trigger-release")
@click.option(
    "--stage",
    default="FULL",
    type=click.Choice(["REMIND_1", "REMIND_2", "PRE_RELEASE", "PARTIAL", "FULL"]),
    help="Target disclosure stage",
)
@click.option(
    "--delay",
    default=0,
    type=int,
    help="Delay in minutes before release executes (0 = next cron)",
)
@click.option(
    "--delay-scope",
    default="full",
    type=click.Choice(["full", "site_only"]),
    help="What to delay: full (integrations+site) or site_only",
)
@click.option(
    "--state-file",
    default="state/current.json",
    help="Path to state file",
)
@click.option(
    "--silent",
    is_flag=True,
    help="Silent mode - minimal output for stealth operations",
)
@click.pass_context
def trigger_release(
    ctx: click.Context,
    stage: str,
    delay: int,
    delay_scope: str,
    state_file: str,
    silent: bool,
) -> None:
    """Manually trigger disclosure escalation (emergency release)."""
    import json
    import secrets

    from ..persistence.state_file import load_state, save_state

    root = ctx.obj["root"]
    state_path = root / state_file

    state = load_state(state_path)
    now = datetime.now(timezone.utc)

    old_state = state.escalation.state

    # Generate client token for fake success display
    client_token = secrets.token_urlsafe(16)

    # Calculate execute time
    execute_after = now + timedelta(minutes=delay)

    # Set release config — silent = shadow mode = triggered
    state.release.triggered = silent
    state.release.trigger_time_iso = now.isoformat()
    state.release.target_stage = stage
    state.release.delay_minutes = delay
    state.release.delay_scope = delay_scope
    state.release.execute_after_iso = execute_after.isoformat()
    state.release.client_token = client_token

    if delay == 0:
        # Immediate: set state now
        state.escalation.state = stage
        state.escalation.state_entered_at_iso = now.isoformat()
        state.escalation.last_transition_rule_id = "MANUAL_TRIGGER"

        # Set deadline to past (overdue)
        state.timer.deadline_iso = (now - timedelta(hours=1)).isoformat()
        state.timer.now_iso = now.isoformat()
        state.timer.time_to_deadline_minutes = -60
        state.timer.overdue_minutes = 60
    # else: delayed - tick will handle state change after execute_after_iso

    # CRITICAL: Clear renewal flag so tick doesn't reset state back to OK
    state.renewal.renewed_this_tick = False

    state.meta.updated_at_iso = now.isoformat()

    save_state(state, state_path)

    # Append to audit log
    audit_path = root / "audit" / "ledger.ndjson"
    audit_entry = {
        "event_type": "manual_release",
        "timestamp": now.isoformat(),
        "tick_id": f"M-{now.strftime('%Y%m%dT%H%M%S')}-RELEASE",
        "previous_state": old_state,
        "new_state": stage if delay == 0 else f"{stage}(delayed:{delay}m)",
        "trigger": "MANUAL",
        "silent": silent,
        "delay_minutes": delay,
        "delay_scope": delay_scope,
        "execute_after": execute_after.isoformat(),
        "client_token": client_token,
    }

    with open(audit_path, "a") as f:
        f.write(json.dumps(audit_entry) + "\n")

    if not silent:
        click.secho(f"⚠️  RELEASE TRIGGERED", fg="red", bold=True)
        click.echo(f"  Previous state: {old_state}")
        click.echo(f"  Target state: {stage}")
        click.echo(f"  Delay: {delay} minutes ({delay_scope})")
        click.echo(f"  Execute after: {execute_after.isoformat()}")
        click.echo(f"  Client token: {client_token}")
    else:
        # Output token for client-side fake success
        click.echo(f"{client_token}")
