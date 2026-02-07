"""
CLI init command — project initialization and scaffolding.

Usage:
    python -m src.main init [--project NAME] [--github-repo OWNER/REPO] [--deadline-hours 48]
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import click


@click.command("init")
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
