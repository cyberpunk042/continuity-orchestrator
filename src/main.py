"""
Continuity Orchestrator — CLI Entry Point

Usage:
    python -m src.main tick [--dry-run]
    python -m src.main status
    python -m src.main set-deadline --hours N
"""

from __future__ import annotations

# Load .env file FIRST, before any other imports that might read env vars
from pathlib import Path
from dotenv import load_dotenv

# Find .env in project root
_project_root = Path(__file__).parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import click

from .models.state import State
from .policy.loader import load_policy
from .persistence.state_file import load_state, save_state
from .persistence.audit import AuditWriter
from .engine.tick import run_tick
from .logging_config import setup_logging
from .cli.test import test as test_group
from .cli.deploy import export_secrets, explain_stages, simulate_timeline
from .cli.site import build_site
from .cli.mirror import mirror_status, mirror_sync, mirror_clean
from .cli.config import check_config, config_status, generate_config
from .cli.ops import health, metrics_cmd, retry_queue_cmd, circuit_breakers_cmd

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
        from .models.state import (
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
        click.secho("✅ State reset to OK", fg="green")



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


@cli.command("trigger-release")
@click.option(
    "--stage",
    default="FULL",
    type=click.Choice(["PARTIAL", "FULL"]),
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


# Site commands — extracted to src/cli/site.py
cli.add_command(build_site)

# Config commands — extracted to src/cli/config.py
cli.add_command(check_config)
cli.add_command(config_status)
cli.add_command(generate_config)

# Ops commands — extracted to src/cli/ops.py
cli.add_command(health)
cli.add_command(metrics_cmd)
cli.add_command(retry_queue_cmd)
cli.add_command(circuit_breakers_cmd)

# ─── Mirror Commands ──────────────────────────────────────────────

# Mirror commands — extracted to src/cli/mirror.py
cli.add_command(mirror_status)
cli.add_command(mirror_sync)
cli.add_command(mirror_clean)

@cli.command("init")
@click.option(
    "--project",
    "-p",
    default="continuity",
    help="Name for this project",
)
@click.option(
    "--github-repo",
    "-g",
    default="owner/repo",
    help="GitHub repository in owner/repo format",
)
@click.option(
    "--deadline-hours",
    "-d",
    default=48,
    type=int,
    help="Hours until initial deadline",
)
@click.option(
    "--operator-email",
    "-e",
    default="operator@example.com",
    help="Email address for the primary operator",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Overwrite existing state file",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Skip prompts, use defaults",
)
@click.pass_context
def init(
    ctx: click.Context,
    project: str,
    github_repo: str,
    deadline_hours: int,
    operator_email: str,
    force: bool,
    non_interactive: bool,
) -> None:
    """Initialize a new Continuity Orchestrator project."""
    import json
    import shutil
    
    root = ctx.obj["root"]
    state_path = root / "state" / "current.json"
    
    # Check if state already exists
    if state_path.exists() and not force:
        click.secho(f"❌ State file already exists: {state_path}", fg="red")
        click.echo("   Use --force to overwrite")
        raise SystemExit(1)
    
    click.echo()
    click.secho("🚀 Initializing Continuity Orchestrator", fg="cyan", bold=True)
    click.echo()
    
    # Create directories
    dirs = ["state", "audit", "content/articles", "public"]
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)
        click.echo(f"  📁 Created {d}/")
    
    # Initialize state
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(hours=deadline_hours)
    
    state_data = {
        "meta": {
            "schema_version": 1,
            "project": project,
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
            "time_to_deadline_minutes": deadline_hours * 60,
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
                "github_surface": True,
                "article_publish": True,
                "persistence_api": False
            },
            "routing": {
                "github_repository": github_repo,
                "operator_email": operator_email,
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
    
    with open(state_path, "w") as f:
        json.dump(state_data, f, indent=4)
    click.secho(f"  ✅ Created state/current.json", fg="green")
    
    # Initialize audit log
    audit_path = root / "audit" / "ledger.ndjson"
    if not audit_path.exists() or force:
        init_entry = {
            "event_type": "init",
            "timestamp": now.isoformat(),
            "tick_id": f"INIT-{now.strftime('%Y%m%dT%H%M%S')}",
            "project": project,
            "github_repository": github_repo,
            "operator_email": operator_email,
            "deadline": deadline.isoformat(),
        }
        with open(audit_path, "w") as f:
            f.write(json.dumps(init_entry) + "\n")
        click.secho(f"  ✅ Created audit/ledger.ndjson", fg="green")
    
    # Create sample content manifest
    manifest_path = root / "content" / "manifest.yaml"
    if not manifest_path.exists() or force:
        manifest_content = f'''# Content Manifest
# Defines article visibility rules and stage-specific behavior

version: 1

articles:
  - slug: about
    title: "About {project}"
    visibility:
      min_stage: OK
      include_in_nav: true
      pin_to_top: false
    meta:
      description: "Project overview and objectives"
      author: "Operator"
      tags: ["info"]

defaults:
  visibility:
    min_stage: FULL
    include_in_nav: false

stages:
  OK:
    show_countdown: false
  REMIND_1:
    banner: "⏰ Reminder: Deadline approaching"
    banner_class: warning
    show_countdown: true
  REMIND_2:
    banner: "⚠️ Final warning: Action required"
    banner_class: warning
    show_countdown: true
  PRE_RELEASE:
    banner: "🔴 Pre-release mode active"
    banner_class: alert
    show_countdown: true
  PARTIAL:
    banner: "📢 Partial disclosure in effect"
    banner_class: critical
    show_countdown: true
  FULL:
    banner: "🚨 Full disclosure mode"
    banner_class: critical
    show_countdown: false
'''
        with open(manifest_path, "w") as f:
            f.write(manifest_content)
        click.secho(f"  ✅ Created content/manifest.yaml", fg="green")
    
    click.echo()
    click.secho("✅ Initialization complete!", fg="green", bold=True)
    click.echo()
    
    # Summary
    click.echo("📋 Summary:")
    click.echo(f"   Project:    {project}")
    click.echo(f"   Repository: {github_repo}")
    click.echo(f"   Operator:   {operator_email}")
    click.echo(f"   Deadline:   {deadline.isoformat()} ({deadline_hours}h from now)")
    click.echo()
    
    # Next steps
    click.secho("📖 Next steps:", bold=True)
    click.echo()
    click.echo("  1. Set GitHub secrets:")
    click.echo(f"     → Go to https://github.com/{github_repo}/settings/secrets/actions")
    click.echo("     → Add RENEWAL_SECRET (your renewal code)")
    click.echo()
    click.echo("  2. Configure adapters (optional):")
    click.echo("     → python -m src.main check-config")
    click.echo()
    click.echo("  3. Create content:")
    click.echo("     → Add articles to content/articles/")
    click.echo("     → Update content/manifest.yaml")
    click.echo()
    click.echo("  4. Build and deploy:")
    click.echo("     → python -m src.main build-site")
    click.echo("     → git push origin main")
    click.echo()


# Test commands — extracted to src/cli/test.py
cli.add_command(test_group)


# Deployment commands — extracted to src/cli/deploy.py
cli.add_command(export_secrets)
cli.add_command(explain_stages)
cli.add_command(simulate_timeline)


if __name__ == "__main__":
    cli()
