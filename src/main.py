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
    
    # Set release config
    state.release.triggered = True
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


@cli.command("generate-config")
@click.option("--output", "-o", help="Output file (default: stdout)")
@click.pass_context
def generate_config(ctx: click.Context, output: str) -> None:
    """
    Generate a CONTINUITY_CONFIG template.
    
    This creates a JSON template you can use as a single GitHub secret
    instead of configuring each adapter secret individually.
    """
    from .config.loader import generate_master_config_template
    
    template = generate_master_config_template()
    
    if output:
        with open(output, "w") as f:
            f.write(template)
        click.secho(f"✅ Template written to {output}", fg="green")
        click.echo()
        click.echo("Next steps:")
        click.echo("  1. Edit the file with your credentials")
        click.echo("  2. Add as GitHub secret named CONTINUITY_CONFIG")
        click.echo("     (paste the entire JSON content)")
    else:
        click.echo()
        click.secho("CONTINUITY_CONFIG Template", bold=True)
        click.echo("─" * 40)
        click.echo()
        click.echo(template)
        click.echo()
        click.echo("─" * 40)
        click.echo()
        click.echo("To use this:")
        click.echo("  1. Copy the JSON above")
        click.echo("  2. Fill in your credentials")
        click.echo("  3. Go to GitHub → Settings → Secrets → Actions")
        click.echo("  4. Create secret named: CONTINUITY_CONFIG")
        click.echo("  5. Paste the JSON as the value")


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


@cli.command("health")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--state-file", default="state/current.json", help="Path to state file")
@click.pass_context
def health(ctx: click.Context, as_json: bool, state_file: str) -> None:
    """Check system health status."""
    from .observability.health import HealthChecker, HealthStatus
    
    root = ctx.obj["root"]
    state_path = root / state_file
    audit_path = root / "audit" / "ledger.ndjson"
    
    checker = HealthChecker(state_path=state_path, audit_path=audit_path)
    result = checker.check()
    
    if as_json:
        import json
        click.echo(json.dumps(result.to_dict(), indent=2))
        return
    
    # Status header
    status_colors = {
        HealthStatus.HEALTHY: ("✅", "green"),
        HealthStatus.DEGRADED: ("⚠️", "yellow"),
        HealthStatus.UNHEALTHY: ("❌", "red"),
    }
    icon, color = status_colors.get(result.status, ("❓", "white"))
    
    click.echo()
    click.secho(f"{icon} System Health: {result.status.value.upper()}", fg=color, bold=True)
    click.echo(f"   Uptime: {result.uptime_seconds:.0f}s")
    click.echo()
    
    # Components
    click.echo("Components:")
    for component in result.components:
        c_icon, c_color = status_colors.get(component.status, ("❓", "white"))
        click.echo(f"  {c_icon} ", nl=False)
        click.secho(f"{component.name}", fg=c_color, bold=True, nl=False)
        click.echo(f": {component.message}")
        if component.latency_ms:
            click.echo(f"      Latency: {component.latency_ms:.1f}ms")
    
    click.echo()
    
    # Exit code based on health
    if result.status == HealthStatus.UNHEALTHY:
        raise SystemExit(1)


@cli.command("metrics")
@click.option("--format", "output_format", type=click.Choice(["prometheus", "json"]), default="prometheus")
@click.pass_context
def metrics_cmd(ctx: click.Context, output_format: str) -> None:
    """Export metrics for monitoring."""
    from .observability.metrics import metrics
    
    if output_format == "json":
        import json
        click.echo(json.dumps(metrics.export_json(), indent=2))
    else:
        click.echo(metrics.export_prometheus())


@cli.command("retry-queue")
@click.option("--action", type=click.Choice(["status", "clear"]), default="status")
@click.pass_context
def retry_queue_cmd(ctx: click.Context, action: str) -> None:
    """Manage the retry queue for failed actions."""
    from .reliability.retry_queue import RetryQueue
    
    root = ctx.obj["root"]
    queue = RetryQueue(root / "state" / "retry_queue.json")
    
    if action == "status":
        stats = queue.get_stats()
        click.echo()
        click.echo("📋 Retry Queue Status")
        click.echo()
        click.echo(f"  Total items:   {stats['total_items']}")
        click.echo(f"  Pending now:   {stats['pending_now']}")
        
        if stats["by_adapter"]:
            click.echo()
            click.echo("  By adapter:")
            for adapter, count in stats["by_adapter"].items():
                click.echo(f"    {adapter}: {count}")
        
        click.echo()
    
    elif action == "clear":
        count = queue.clear()
        click.secho(f"✅ Cleared {count} items from retry queue", fg="green")


@cli.command("circuit-breakers")
@click.option("--reset", "do_reset", is_flag=True, help="Reset all circuit breakers")
@click.pass_context
def circuit_breakers_cmd(ctx: click.Context, do_reset: bool) -> None:
    """View and manage circuit breakers."""
    from .reliability.circuit_breaker import get_registry, CircuitState
    
    registry = get_registry()
    
    if do_reset:
        registry.reset_all()
        click.secho("✅ All circuit breakers reset", fg="green")
        return
    
    stats = registry.get_all_stats()
    
    if not stats:
        click.echo("No circuit breakers registered")
        return
    
    click.echo()
    click.echo("🔌 Circuit Breakers")
    click.echo()
    
    for name, data in stats.items():
        state = data["state"]
        color = {
            "closed": "green",
            "open": "red",
            "half_open": "yellow",
        }.get(state, "white")
        
        icon = {
            "closed": "🟢",
            "open": "🔴",
            "half_open": "🟡",
        }.get(state, "⚪")
        
        click.echo(f"  {icon} ", nl=False)
        click.secho(f"{name}", fg=color, bold=True, nl=False)
        click.echo(f": {state}")
        
        stats_data = data.get("stats", {})
        click.echo(f"      Success: {stats_data.get('success_count', 0)} | "
                   f"Failures: {stats_data.get('failure_count', 0)} | "
                   f"Rejected: {stats_data.get('rejected_count', 0)}")
    
    click.echo()


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


# =============================================================================
# TEST COMMANDS — Verify each adapter works
# =============================================================================

@cli.group()
def test():
    """Test individual adapters with real API calls."""
    pass


@test.command("email")
@click.option("--to", "-t", help="Email address to send to (default: OPERATOR_EMAIL)")
@click.option("--subject", "-s", default="Continuity Orchestrator Test", help="Email subject")
@click.option("--body", "-b", default="This is a test email from Continuity Orchestrator.", help="Email body")
def test_email(to: str, subject: str, body: str):
    """Send a test email via Resend."""
    import os
    
    # Check configuration
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        click.secho("❌ RESEND_API_KEY not set", fg="red")
        click.echo("   Set it in your .env file or export it:")
        click.echo("   export RESEND_API_KEY=re_xxxxx")
        raise SystemExit(1)
    
    to_email = to or os.environ.get("OPERATOR_EMAIL")
    if not to_email:
        click.secho("❌ No email address specified", fg="red")
        click.echo("   Use --to <email> or set OPERATOR_EMAIL in .env")
        raise SystemExit(1)
    
    from_email = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    
    click.echo()
    click.secho("📧 Testing Email (Resend)", bold=True)
    click.echo(f"   From: {from_email}")
    click.echo(f"   To: {to_email}")
    click.echo(f"   Subject: {subject}")
    click.echo()
    
    try:
        import resend
        resend.api_key = api_key
        
        result = resend.Emails.send({
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "text": body,
            "html": f"<p>{body}</p><p><small>Sent by Continuity Orchestrator test command.</small></p>",
        })
        
        email_id = result.get("id") if isinstance(result, dict) else str(result)
        click.secho(f"✅ Email sent successfully!", fg="green")
        click.echo(f"   Email ID: {email_id}")
        click.echo()
        click.echo(f"   Check your inbox at {to_email}")
        
    except ImportError:
        click.secho("❌ resend package not installed", fg="red")
        click.echo("   pip install resend")
        raise SystemExit(1)
    except Exception as e:
        click.secho(f"❌ Email failed: {e}", fg="red")
        raise SystemExit(1)


@test.command("sms")
@click.option("--to", "-t", help="Phone number to send to (default: OPERATOR_SMS)")
@click.option("--message", "-m", default="Continuity Orchestrator test message", help="SMS message")
def test_sms(to: str, message: str):
    """Send a test SMS via Twilio."""
    import os
    
    # Check configuration
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")
    
    missing = []
    if not account_sid:
        missing.append("TWILIO_ACCOUNT_SID")
    if not auth_token:
        missing.append("TWILIO_AUTH_TOKEN")
    if not from_number:
        missing.append("TWILIO_FROM_NUMBER")
    
    if missing:
        click.secho(f"❌ Missing: {', '.join(missing)}", fg="red")
        click.echo("   Set these in your .env file")
        raise SystemExit(1)
    
    to_number = to or os.environ.get("OPERATOR_SMS")
    if not to_number:
        click.secho("❌ No phone number specified", fg="red")
        click.echo("   Use --to <number> or set OPERATOR_SMS in .env")
        raise SystemExit(1)
    
    click.echo()
    click.secho("📱 Testing SMS (Twilio)", bold=True)
    click.echo(f"   From: {from_number}")
    click.echo(f"   To: {to_number}")
    click.echo(f"   Message: {message}")
    click.echo()
    
    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        
        result = client.messages.create(
            body=message,
            from_=from_number,
            to=to_number,
        )
        
        click.secho(f"✅ SMS sent successfully!", fg="green")
        click.echo(f"   Message SID: {result.sid}")
        click.echo(f"   Status: {result.status}")
        
    except ImportError:
        click.secho("❌ twilio package not installed", fg="red")
        click.echo("   pip install twilio")
        raise SystemExit(1)
    except Exception as e:
        click.secho(f"❌ SMS failed: {e}", fg="red")
        raise SystemExit(1)


@test.command("webhook")
@click.option("--url", "-u", required=True, help="Webhook URL to POST to")
@click.option("--payload", "-p", default='{"test": true, "source": "continuity-orchestrator"}', help="JSON payload")
def test_webhook(url: str, payload: str):
    """Send a test webhook POST."""
    import json
    
    click.echo()
    click.secho("🔗 Testing Webhook", bold=True)
    click.echo(f"   URL: {url}")
    click.echo(f"   Payload: {payload}")
    click.echo()
    
    try:
        import httpx
        
        data = json.loads(payload)
        response = httpx.post(url, json=data, timeout=30)
        
        if response.status_code < 400:
            click.secho(f"✅ Webhook successful!", fg="green")
            click.echo(f"   Status: {response.status_code}")
            click.echo(f"   Response: {response.text[:200]}")
        else:
            click.secho(f"⚠️ Webhook returned error", fg="yellow")
            click.echo(f"   Status: {response.status_code}")
            click.echo(f"   Response: {response.text[:200]}")
        
    except ImportError:
        click.secho("❌ httpx package not installed", fg="red")
        click.echo("   pip install httpx")
        raise SystemExit(1)
    except json.JSONDecodeError:
        click.secho("❌ Invalid JSON payload", fg="red")
        raise SystemExit(1)
    except Exception as e:
        click.secho(f"❌ Webhook failed: {e}", fg="red")
        raise SystemExit(1)


@test.command("github")
@click.option("--repo", "-r", help="Repository (owner/repo) — default: GITHUB_REPOSITORY")
def test_github(repo: str):
    """Verify GitHub token and repository access."""
    import os
    
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        click.secho("❌ GITHUB_TOKEN not set", fg="red")
        click.echo("   Set it in your .env file")
        raise SystemExit(1)
    
    repository = repo or os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        click.secho("❌ No repository specified", fg="red")
        click.echo("   Use --repo owner/repo or set GITHUB_REPOSITORY in .env")
        raise SystemExit(1)
    
    click.echo()
    click.secho("🐙 Testing GitHub", bold=True)
    click.echo(f"   Token: {token[:10]}...")
    click.echo(f"   Repository: {repository}")
    click.echo()
    
    try:
        import httpx
        
        # Test token by getting user info
        headers = {"Authorization": f"Bearer {token}"}
        
        user_response = httpx.get("https://api.github.com/user", headers=headers, timeout=30)
        if user_response.status_code != 200:
            click.secho(f"❌ Token invalid: {user_response.status_code}", fg="red")
            raise SystemExit(1)
        
        user_data = user_response.json()
        click.secho(f"✅ Token valid!", fg="green")
        click.echo(f"   User: {user_data.get('login')}")
        
        # Test repository access
        repo_response = httpx.get(
            f"https://api.github.com/repos/{repository}",
            headers=headers,
            timeout=30,
        )
        
        if repo_response.status_code == 200:
            repo_data = repo_response.json()
            click.secho(f"✅ Repository accessible!", fg="green")
            click.echo(f"   Name: {repo_data.get('full_name')}")
            click.echo(f"   Visibility: {repo_data.get('visibility')}")
        elif repo_response.status_code == 404:
            click.secho(f"⚠️ Repository not found or no access", fg="yellow")
            click.echo(f"   Check repository exists and token has permissions")
        else:
            click.secho(f"⚠️ Repository check failed: {repo_response.status_code}", fg="yellow")
        
    except ImportError:
        click.secho("❌ httpx package not installed", fg="red")
        click.echo("   pip install httpx")
        raise SystemExit(1)
    except Exception as e:
        click.secho(f"❌ GitHub test failed: {e}", fg="red")
        raise SystemExit(1)


@test.command("all")
def test_all():
    """Show configuration status for all adapters."""
    from .config.validator import ConfigValidator
    
    click.echo()
    click.secho("🧪 Adapter Configuration Status", bold=True)
    click.echo()
    
    validator = ConfigValidator()
    results = validator.validate_all()
    
    for name, status in sorted(results.items()):
        if status.configured:
            if status.mode == "real":
                click.secho(f"  ✅ {name}", fg="green", nl=False)
                click.echo(f" — ready (real mode)")
            else:
                click.secho(f"  ⚠️  {name}", fg="yellow", nl=False)
                click.echo(f" — configured but mock mode enabled")
        else:
            click.secho(f"  ❌ {name}", fg="red", nl=False)
            if status.missing:
                click.echo(f" — missing: {', '.join(status.missing)}")
            else:
                click.echo(f" — not configured")
    
    click.echo()
    click.echo("To test an adapter:")
    click.echo("  python -m src.main test email")
    click.echo("  python -m src.main test sms")
    click.echo("  python -m src.main test webhook --url https://example.com/hook")
    click.echo("  python -m src.main test github")
    click.echo()


# =============================================================================
# DEPLOYMENT COMMANDS
# =============================================================================

@cli.command("export-secrets")
@click.option("--format", "-f", type=click.Choice(["text", "gh-cli"]), default="text", help="Output format")
def export_secrets(format: str):
    """Export secrets for GitHub Actions deployment.
    
    Shows which secrets need to be added to your GitHub repository
    for the scheduled tick workflow to run.
    """
    import os
    
    # Read current .env values
    secrets = {
        "RESEND_API_KEY": os.environ.get("RESEND_API_KEY", ""),
        "RESEND_FROM_EMAIL": os.environ.get("RESEND_FROM_EMAIL", ""),
        "TWILIO_ACCOUNT_SID": os.environ.get("TWILIO_ACCOUNT_SID", ""),
        "TWILIO_AUTH_TOKEN": os.environ.get("TWILIO_AUTH_TOKEN", ""),
        "TWILIO_FROM_NUMBER": os.environ.get("TWILIO_FROM_NUMBER", ""),
        "OPERATOR_SMS": os.environ.get("OPERATOR_SMS", ""),
        "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
        "X_API_KEY": os.environ.get("X_API_KEY", ""),
        "X_API_SECRET": os.environ.get("X_API_SECRET", ""),
        "X_ACCESS_TOKEN": os.environ.get("X_ACCESS_TOKEN", ""),
        "X_ACCESS_SECRET": os.environ.get("X_ACCESS_SECRET", ""),
        "REDDIT_CLIENT_ID": os.environ.get("REDDIT_CLIENT_ID", ""),
        "REDDIT_CLIENT_SECRET": os.environ.get("REDDIT_CLIENT_SECRET", ""),
        "REDDIT_USERNAME": os.environ.get("REDDIT_USERNAME", ""),
        "REDDIT_PASSWORD": os.environ.get("REDDIT_PASSWORD", ""),
    }
    
    # Core settings
    core = {
        "OPERATOR_EMAIL": os.environ.get("OPERATOR_EMAIL", ""),
        "PROJECT_NAME": os.environ.get("PROJECT_NAME", ""),
        "ADAPTER_MOCK_MODE": os.environ.get("ADAPTER_MOCK_MODE", "false"),
    }
    
    # Also need RENEWAL_SECRET for the renewal workflow
    renewal_secret = os.environ.get("RENEWAL_SECRET", "")
    
    # RENEWAL_TRIGGER_TOKEN for one-click renewal from website
    renewal_trigger_token = os.environ.get("RENEWAL_TRIGGER_TOKEN", "")
    
    repo = os.environ.get("GITHUB_REPOSITORY", "owner/repo")
    
    click.echo()
    click.secho("🔐 GitHub Actions Secrets", bold=True)
    click.echo()
    click.echo(f"Add these secrets to: https://github.com/{repo}/settings/secrets/actions")
    click.echo()
    
    if format == "gh-cli":
        click.echo("# Run these commands (requires gh CLI):")
        click.echo()
        for name, value in {**core, **secrets}.items():
            if value:
                # Mask the actual value
                click.echo(f'echo "{value}" | gh secret set {name}')
        if renewal_secret:
            click.echo(f'echo "{renewal_secret}" | gh secret set RENEWAL_SECRET')
        else:
            click.echo('# Generate a renewal secret:')
            click.echo('echo "$(openssl rand -hex 16)" | gh secret set RENEWAL_SECRET')
        if renewal_trigger_token:
            click.echo(f'echo "{renewal_trigger_token}" | gh secret set RENEWAL_TRIGGER_TOKEN')
        else:
            click.echo('# RENEWAL_TRIGGER_TOKEN not set - create a fine-grained PAT for one-click renewal')
        click.echo()
    else:
        click.secho("Required secrets:", bold=True)
        click.echo()
        
        # Show which are configured
        click.echo("  Core settings:")
        for name, value in core.items():
            if value:
                masked = value[:4] + "..." if len(value) > 4 else "***"
                click.secho(f"    ✅ {name}", fg="green", nl=False)
                click.echo(f" = {masked}")
            else:
                click.secho(f"    ⬚  {name}", fg="dim", nl=False)
                click.echo(f" = (not set)")
        click.echo()
        
        click.echo("  Adapter credentials (only those you use):")
        for name, value in secrets.items():
            if value:
                masked = value[:6] + "..." if len(value) > 6 else "***"
                click.secho(f"    ✅ {name}", fg="green", nl=False)
                click.echo(f" = {masked}")
        click.echo()
        
        click.echo("  Renewal secret (for manual check-in):")
        if renewal_secret:
            click.secho(f"    ✅ RENEWAL_SECRET", fg="green", nl=False)
            click.echo(f" = {renewal_secret[:6]}...")
        else:
            click.secho(f"    ⚠️  RENEWAL_SECRET", fg="yellow", nl=False)
            click.echo(" = (generate one)")
            click.echo()
            click.echo("    Generate with: python -c \"import secrets; print(secrets.token_hex(16))\"")
        click.echo()
        
        click.echo("  One-click renewal from website (optional but recommended):")
        if renewal_trigger_token:
            click.secho(f"    ✅ RENEWAL_TRIGGER_TOKEN", fg="green", nl=False)
            click.echo(f" = {renewal_trigger_token[:12]}...")
        else:
            click.secho(f"    ⬚  RENEWAL_TRIGGER_TOKEN", fg="dim", nl=False)
            click.echo(" = (not set)")
            click.echo()
            click.echo("    Create a fine-grained PAT at: https://github.com/settings/tokens?type=beta")
            click.echo("    With ONLY 'Actions: Read and write' permission for this repo")
        click.echo()
    
    click.echo()
    click.secho("📋 Quick copy-paste guide:", bold=True)
    click.echo()
    click.echo("1. Go to your repository settings → Secrets → Actions")
    click.echo("2. Click 'New repository secret' for each secret")
    click.echo("3. Copy the name and value from your .env file")
    click.echo()
    click.echo("Alternatively, use the GitHub CLI:")
    click.echo("  python -m src.main export-secrets --format gh-cli")
    click.echo()


@cli.command("explain")
@click.option("--policy-dir", default="policy", help="Path to policy directory")
@click.option("--stage", "-s", help="Show only a specific stage")
@click.pass_context
def explain_stages(ctx: click.Context, policy_dir: str, stage: str):
    """Show what happens at each escalation stage.
    
    Displays the full action plan for every stage, so you can understand
    exactly what will trigger when.
    """
    root = ctx.obj["root"]
    policy_path = root / policy_dir
    
    # Load policy
    policy = load_policy(policy_path)
    
    # Get the plan
    plan = policy.plan
    if not plan:
        click.secho("❌ No plan found", fg="red")
        raise SystemExit(1)
    
    click.echo()
    click.secho("📋 Escalation Plan: " + (plan.plan_id or plan.name or "default"), bold=True)
    click.echo(f"   {plan.description or 'No description'}")
    click.echo()
    
    # Stage order
    stage_order = ["OK", "REMIND_1", "REMIND_2", "PRE_RELEASE", "PARTIAL", "FULL"]
    
    # Filter if specific stage requested
    if stage:
        stage_order = [s for s in stage_order if s.upper() == stage.upper()]
        if not stage_order:
            click.secho(f"❌ Unknown stage: {stage}", fg="red")
            click.echo("   Valid stages: OK, REMIND_1, REMIND_2, PRE_RELEASE, PARTIAL, FULL")
            raise SystemExit(1)
    
    for stage_name in stage_order:
        stage_config = plan.stages.get(stage_name)
        
        if not stage_config:
            continue
        
        # Color based on severity
        if stage_name == "OK":
            color = "green"
            icon = "✅"
        elif stage_name in ["REMIND_1", "REMIND_2"]:
            color = "yellow"
            icon = "⚠️"
        elif stage_name == "PRE_RELEASE":
            color = "yellow"
            icon = "🔔"
        elif stage_name == "PARTIAL":
            color = "red"
            icon = "🚨"
        else:  # FULL
            color = "red"
            icon = "💀"
        
        click.secho(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", bold=True)
        click.secho(f"{icon} {stage_name}", fg=color, bold=True)
        click.echo(f"   {stage_config.description}")
        click.echo()
        
        if not stage_config.actions:
            click.echo("   No actions configured for this stage.")
        else:
            click.echo(f"   Actions ({len(stage_config.actions)}):")
            for action in stage_config.actions:
                adapter_icon = {
                    "email": "📧",
                    "sms": "📱",
                    "x": "🐦",
                    "reddit": "🔴",
                    "webhook": "🔗",
                    "github_surface": "🐙",
                    "article_publish": "📄",
                    "persistence_api": "💾",
                }.get(action.adapter, "⚙️")
                
                click.echo(f"   {adapter_icon} {action.id}")
                click.echo(f"      Adapter: {action.adapter}")
                click.echo(f"      Channel: {action.channel}")
                if action.template:
                    click.echo(f"      Template: {action.template}")
                if hasattr(action, 'constraints') and action.constraints:
                    try:
                        c_dict = action.constraints.model_dump(exclude_defaults=True)
                        if c_dict:
                            constraints = ", ".join(f"{k}={v}" for k, v in c_dict.items())
                            click.echo(f"      Constraints: {constraints}")
                    except Exception:
                        pass
        click.echo()
    
    click.secho("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", bold=True)
    click.echo()
    
    # Show triggers
    click.secho("📅 When do stages trigger?", bold=True)
    click.echo()
    click.echo("   Based on policy/rules.yaml, checked every tick:")
    click.echo()
    
    # Load rules - policy.rules is RulesPolicy, .rules is the list
    try:
        rules_list = policy.rules.rules if hasattr(policy.rules, 'rules') else []
        for rule in rules_list[:10]:  # First 10 rules
            if hasattr(rule, 'then') and rule.then and hasattr(rule.then, 'transition_to') and rule.then.transition_to:
                click.echo(f"   • {rule.id}")
                if hasattr(rule, 'description') and rule.description:
                    click.echo(f"     {rule.description}")
    except Exception:
        click.echo("   (See policy/rules.yaml for full rule definitions)")
    
    click.echo()
    click.echo("To modify this plan: edit policy/plans/default.yaml")
    click.echo("To modify triggers: edit policy/rules.yaml")
    click.echo()


@cli.command("simulate")
@click.option("--hours", "-h", default=72, help="Hours to simulate")
@click.option("--state-file", default="state/current.json", help="Path to state file")
@click.option("--policy-dir", default="policy", help="Path to policy directory")
@click.pass_context
def simulate_timeline(ctx: click.Context, hours: int, state_file: str, policy_dir: str):
    """Simulate the escalation timeline from now.
    
    Shows what would happen if you don't renew - when each stage would trigger.
    """
    root = ctx.obj["root"]
    state_path = root / state_file
    
    if not state_path.exists():
        click.secho("❌ No state file found. Run init first.", fg="red")
        click.echo("   python -m src.main init")
        raise SystemExit(1)
    
    state = load_state(state_path)
    
    click.echo()
    click.secho("🔮 Escalation Timeline Simulation", bold=True)
    click.echo()
    
    deadline = state.timer.deadline_iso
    now = datetime.now(timezone.utc)
    
    # Handle deadline being a string or datetime
    if isinstance(deadline, str):
        from dateutil.parser import parse
        deadline = parse(deadline)
    
    click.echo(f"   Current time:  {now.strftime('%Y-%m-%d %H:%M UTC')}")
    click.echo(f"   Deadline:      {deadline.strftime('%Y-%m-%d %H:%M UTC')}")
    click.echo(f"   Current stage: {state.escalation.state}")
    click.echo()
    
    # Calculate when each stage would trigger based on rules
    minutes_to_deadline = (deadline - now).total_seconds() / 60
    
    click.secho("   If you DON'T renew:", bold=True)
    click.echo()
    
    # These are approximate based on typical rule configuration
    stages = [
        ("OK", "Always", "green"),
        ("REMIND_1", "When < 24h remaining", "yellow"),
        ("REMIND_2", "When < 6h remaining", "yellow"),
        ("PRE_RELEASE", "When < 1h remaining", "yellow"),
        ("PARTIAL", "When deadline passes", "red"),
        ("FULL", "When 24h overdue", "red"),
    ]
    
    for stage_name, when, color in stages:
        if stage_name == state.escalation.state:
            click.secho(f"   → {stage_name}", fg=color, bold=True, nl=False)
            click.echo(f" ← YOU ARE HERE")
        else:
            click.secho(f"     {stage_name}", fg=color, nl=False)
            click.echo(f" — {when}")
    
    click.echo()
    click.echo("   To see what happens at each stage:")
    click.echo("     python -m src.main explain")
    click.echo()
    click.echo("   To renew and reset the deadline:")
    click.echo("     python -m src.main renew --hours 48")
    click.echo()


if __name__ == "__main__":
    cli()
