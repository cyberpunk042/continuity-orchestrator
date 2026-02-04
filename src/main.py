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


@cli.command("renew")
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
    from datetime import timedelta
    import json
    
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


@cli.command("build-site")
@click.option(
    "--output",
    "-o",
    default="public",
    help="Output directory for generated site",
)
@click.option(
    "--clean/--no-clean",
    default=True,
    help="Clean output directory before building",
)
@click.pass_context
def build_site(ctx: click.Context, output: str, clean: bool) -> None:
    """Build static site from current state."""
    from pathlib import Path
    from .site.generator import SiteGenerator
    import json
    
    root = ctx.obj["root"]
    state_path = root / "state" / "current.json"
    
    click.echo(f"Loading state from {state_path}")
    state = load_state(state_path)
    
    # Load audit entries
    audit_path = root / "audit" / "ledger.ndjson"
    audit_entries = []
    if audit_path.exists():
        with open(audit_path, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        audit_entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    
    click.echo(f"Building site to {output}/")
    generator = SiteGenerator(output_dir=root / output)
    result = generator.build(
        state=state,
        audit_entries=audit_entries,
        clean=clean,
    )
    
    click.secho(f"✓ Site built: {result['files_generated']} files", fg="green")
    click.echo(f"  Output: {result['output_dir']}")
    
    for f in result['files'][:5]:
        click.echo(f"  - {Path(f).name}")
    
    if len(result['files']) > 5:
        click.echo(f"  ... and {len(result['files']) - 5} more")


@cli.command("check-config")
@click.pass_context
def check_config(ctx: click.Context) -> None:
    """Check adapter configuration status."""
    from .config.validator import ConfigValidator
    
    validator = ConfigValidator()
    results = validator.validate_all()
    
    click.echo("\n📋 Adapter Configuration Status\n")
    
    configured = []
    not_configured = []
    
    for name, status in sorted(results.items()):
        if status.configured:
            configured.append((name, status))
            click.secho(f"  ✓ {name}", fg="green", nl=False)
            click.echo(f" — {status.mode} mode")
        else:
            not_configured.append((name, status))
            click.secho(f"  ✗ {name}", fg="red", nl=False)
            if status.missing:
                click.echo(f" — missing: {', '.join(status.missing)}")
            else:
                click.echo(f" — not configured")
    
    click.echo()
    click.secho(f"Summary: {len(configured)} configured, {len(not_configured)} not configured", bold=True)
    
    if not_configured:
        click.echo("\n📖 Setup Guide:\n")
        for name, status in not_configured:
            if status.guidance:
                click.echo(f"  {name}:")
                click.echo(f"    → {status.guidance}")


@cli.command("status")
@click.option(
    "--state-file",
    default="state/current.json",
    help="Path to state file",
)
@click.pass_context
def status(ctx: click.Context, state_file: str) -> None:
    """Show current system status."""
    root = ctx.obj["root"]
    state_path = root / state_file
    
    state = load_state(state_path)
    
    # Determine color based on stage
    stage = state.escalation.state
    color_map = {
        "OK": "green",
        "REMIND_1": "yellow",
        "REMIND_2": "yellow", 
        "PRE_RELEASE": "red",
        "PARTIAL": "magenta",
        "FULL": "red",
    }
    color = color_map.get(stage, "white")
    
    click.echo("\n📊 Continuity Orchestrator Status\n")
    click.echo(f"  Project:    {state.meta.project}")
    click.secho(f"  Stage:      {stage}", fg=color, bold=True)
    click.echo(f"  Armed:      {'Yes' if state.mode.armed else 'No'}")
    click.echo(f"  Deadline:   {state.timer.deadline_iso}")
    
    if state.timer.time_to_deadline_minutes > 0:
        hours = state.timer.time_to_deadline_minutes // 60
        mins = state.timer.time_to_deadline_minutes % 60
        click.echo(f"  Remaining:  {hours}h {mins}m")
    elif state.timer.overdue_minutes > 0:
        click.secho(f"  Overdue:    {state.timer.overdue_minutes} minutes", fg="red")
    
    click.echo(f"  Renewals:   {state.renewal.renewal_count or 0}")
    click.echo(f"  Updated:    {state.meta.updated_at_iso}")
    click.echo()


if __name__ == "__main__":
    cli()
