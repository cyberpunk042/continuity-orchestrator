"""
Continuity Orchestrator — CLI Entry Point

Usage:
    python -m src.main tick [--dry-run]
    python -m src.main status
    python -m src.main set-deadline --hours N
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import click

from .models.state import State
from .policy.loader import load_policy
from .persistence.state_file import load_state, save_state
from .persistence.audit import AuditWriter
from .engine.tick import run_tick
from .logging_config import setup_logging

# Initialize logging
setup_logging()


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Continuity Orchestrator — Policy-first automation system."""
    ctx.ensure_object(dict)
    ctx.obj["root"] = get_project_root()


@cli.command()
@click.option("--state-file", default="state/current.json", help="Path to state file")
@click.option("--policy-dir", default="policy", help="Path to policy directory")
@click.option("--audit-file", default="audit/ledger.ndjson", help="Path to audit ledger")
@click.option("--dry-run", is_flag=True, help="Don't persist changes")
@click.pass_context
def tick(
    ctx: click.Context,
    state_file: str,
    policy_dir: str,
    audit_file: str,
    dry_run: bool,
) -> None:
    """Execute a single tick of the continuity engine."""
    root = ctx.obj["root"]
    state_path = root / state_file
    policy_path = root / policy_dir
    audit_path = root / audit_file

    click.echo(f"Loading state from {state_path}")
    state = load_state(state_path)

    click.echo(f"Loading policy from {policy_path}")
    policy = load_policy(policy_path)

    audit_writer: Optional[AuditWriter] = None
    if not dry_run:
        audit_writer = AuditWriter(audit_path)

    click.echo("Running tick...")
    result = run_tick(state, policy, audit_writer=audit_writer, dry_run=dry_run)

    click.echo("")
    click.echo(f"  Tick ID: {result.tick_id}")
    click.echo(f"  Matched rules: {result.matched_rules}")
    click.echo(f"  State: {result.previous_state} → {result.new_state}")
    if result.state_changed:
        click.secho("  ⚡ State transitioned!", fg="yellow", bold=True)
    click.echo(f"  Actions selected: {result.actions_selected}")
    click.echo(f"  Actions executed: {result.actions_executed}")

    if not dry_run:
        click.echo(f"\nSaving state to {state_path}")
        save_state(state, state_path)
        click.secho("✓ State persisted", fg="green")
    else:
        click.secho("\n(Dry run — no changes persisted)", fg="cyan")


@cli.command()
@click.option("--state-file", default="state/current.json")
@click.pass_context
def status(ctx: click.Context, state_file: str) -> None:
    """Show current state."""
    root = ctx.obj["root"]
    state_path = root / state_file

    state = load_state(state_path)

    click.echo(f"Project:      {state.meta.project}")
    click.echo(f"State ID:     {state.meta.state_id}")
    click.echo(f"Plan:         {state.meta.plan_id}")
    click.echo("")
    click.echo(f"Escalation:   {state.escalation.state}")
    click.echo(f"Mode:         {state.mode.name}")
    click.echo(f"Armed:        {state.mode.armed}")
    click.echo("")
    click.echo(f"Deadline:     {state.timer.deadline_iso}")
    click.echo(f"Last updated: {state.meta.updated_at_iso}")

    # Compute time remaining
    now = datetime.now(timezone.utc)
    try:
        from dateutil import parser as date_parser
        deadline = date_parser.isoparse(state.timer.deadline_iso)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        delta = deadline - now
        minutes = int(delta.total_seconds() / 60)
        if minutes >= 0:
            click.echo(f"Time left:    {minutes} minutes ({minutes // 60}h {minutes % 60}m)")
        else:
            click.secho(f"OVERDUE:      {abs(minutes)} minutes", fg="red", bold=True)
    except Exception:
        pass


@cli.command("set-deadline")
@click.option("--hours", type=float, required=True, help="Hours from now")
@click.option("--state-file", default="state/current.json")
@click.pass_context
def set_deadline(ctx: click.Context, hours: float, state_file: str) -> None:
    """Set the countdown deadline."""
    root = ctx.obj["root"]
    state_path = root / state_file

    state = load_state(state_path)

    new_deadline = datetime.now(timezone.utc) + timedelta(hours=hours)
    state.timer.deadline_iso = new_deadline.isoformat()

    save_state(state, state_path)
    click.echo(f"Deadline set to {new_deadline.isoformat()}")
    click.echo(f"  ({hours} hours from now)")


@cli.command()
@click.option("--state-file", default="state/current.json")
@click.pass_context
def reset(ctx: click.Context, state_file: str) -> None:
    """Reset escalation state to OK."""
    root = ctx.obj["root"]
    state_path = root / state_file

    state = load_state(state_path)

    state.escalation.state = "OK"
    state.escalation.state_entered_at_iso = datetime.now(timezone.utc).isoformat()
    state.escalation.last_transition_rule_id = None
    state.actions.executed = {}
    state.actions.last_tick_actions = []

    save_state(state, state_path)
    click.secho("State reset to OK", fg="green")


if __name__ == "__main__":
    cli()
