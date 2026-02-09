"""
CLI core commands — state lifecycle operations (reset, renew, trigger-release).

Usage:
    python -m src.main reset [--full] [--hours 48] [--yes]
    python -m src.main reset --full --include-content [--purge-history] [--yes]
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
@click.option("--include-content", is_flag=True, help="Also wipe all articles and media (requires --full)")
@click.option("--purge-history", is_flag=True, help="Purge media from git history (requires --include-content)")
@click.option("--decrypt-content", is_flag=True, help="Decrypt content in backup (requires --backup + --include-content)")
@click.option("--scaffold/--no-scaffold", default=True, help="Regenerate default articles after content wipe")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def reset(
    ctx: click.Context,
    state_file: str,
    full: bool,
    backup: bool,
    hours: int,
    include_content: bool,
    purge_history: bool,
    decrypt_content: bool,
    scaffold: bool,
    yes: bool,
) -> None:
    """Reset state to OK or perform full factory reset.

    Without --full: Just resets escalation state to OK.
    With --full: Creates fresh state and clears audit log.
    With --full --include-content: Also wipes all articles and media.
    With --full --include-content --purge-history: Also purges media from git history.
    """
    import json
    import shutil
    import subprocess as _sp

    from ..persistence.state_file import load_state, save_state

    root = ctx.obj["root"]
    state_path = root / state_file
    audit_path = root / "audit" / "ledger.ndjson"
    backup_dir = root / "backups"
    articles_dir = root / "content" / "articles"
    media_dir = root / "content" / "media"

    # ── Validate flag dependencies ────────────────────────────────
    if include_content and not full:
        raise click.ClickException("--include-content requires --full")
    if purge_history and not include_content:
        raise click.ClickException("--purge-history requires --include-content")

    if full and not yes:
        click.secho("⚠️  FULL RESET will:", fg="yellow", bold=True)
        click.echo("  - Create fresh state with new deadline")
        click.echo("  - Clear the audit log")
        if include_content:
            click.echo("  - Delete all articles and media")
            click.echo("  - Reset content manifests")
        if purge_history:
            click.echo("  - Purge media from git history (rewrites commits)")
        if backup:
            click.echo("  - Backup existing files first")
        if not click.confirm("Continue?"):
            click.echo("Cancelled.")
            return

    now = datetime.now(timezone.utc)

    # Backup existing state if requested
    if backup and state_path.exists():
        from .backup import create_backup_archive

        archive_path, manifest = create_backup_archive(
            root,
            include_state=True,
            include_audit=full and audit_path.exists(),
            include_articles=include_content,
            include_media=include_content,
            include_policy=True,
            decrypt_content=decrypt_content and include_content,
            trigger="factory_reset",
        )
        size_kb = archive_path.stat().st_size / 1024
        click.echo(f"  📦 Backed up to: {archive_path.name} ({size_kb:.1f} KB)")

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

        # ── Content cleanup ───────────────────────────────────────
        if include_content:
            click.echo("")
            click.secho("  Content cleanup:", fg="yellow")

            # Wipe articles
            deleted_articles = 0
            if articles_dir.exists():
                for f in articles_dir.glob("*.json"):
                    f.unlink()
                    deleted_articles += 1
            click.echo(f"    Deleted {deleted_articles} article(s)")

            # Wipe encrypted media files (.enc only — README stays)
            deleted_media = 0
            freed_bytes = 0
            if media_dir.exists():
                for f in media_dir.glob("*.enc"):
                    freed_bytes += f.stat().st_size
                    f.unlink()
                    deleted_media += 1
            click.echo(f"    Deleted {deleted_media} media file(s) ({freed_bytes / 1024:.0f} KB)")

            # Reset media manifest
            media_manifest = media_dir / "manifest.json"
            media_manifest.parent.mkdir(parents=True, exist_ok=True)
            media_manifest.write_text(json.dumps({"version": 1, "media": []}, indent=2) + "\n")
            click.echo("    Reset media manifest")

            # Reset content manifest — preserve stages/defaults, clear articles
            manifest_path = root / "content" / "manifest.yaml"
            if manifest_path.exists():
                try:
                    import yaml
                    manifest = yaml.safe_load(manifest_path.read_text()) or {}
                    manifest["articles"] = []
                    manifest_path.write_text(yaml.dump(
                        manifest, default_flow_style=False, sort_keys=False
                    ))
                except Exception as e:
                    click.secho(f"    ⚠️ Could not reset manifest.yaml: {e}", fg="yellow")
            click.echo("    Reset content manifest")

            click.secho("  ✅ Content wiped", fg="green")

            # Regenerate scaffold articles
            if scaffold:
                from ..content.scaffold import generate_scaffold
                result = generate_scaffold(root)
                created = result["created"]
                if created:
                    click.echo(f"    📄 Scaffold: regenerated {', '.join(created)}")
                else:
                    click.echo("    📄 Scaffold: no articles to create")

        # ── Git history purge ─────────────────────────────────────
        if purge_history:
            click.echo("")
            click.secho("  Git history purge:", fg="yellow")

            # Check for git-filter-repo
            if not shutil.which("git-filter-repo"):
                click.secho(
                    "  ❌ git-filter-repo is not installed.\n"
                    "     Install with: pip install git-filter-repo",
                    fg="red",
                )
            else:
                # Pre-check: clean working tree required
                status_result = _sp.run(
                    ["git", "status", "--porcelain"],
                    cwd=str(root), capture_output=True, text=True, timeout=10,
                )
                if status_result.stdout.strip():
                    # Stage and commit everything first (we just did a reset)
                    click.echo("    Staging post-reset changes...")
                    _sp.run(["git", "add", "-A"], cwd=str(root), timeout=10)
                    _sp.run(
                        ["git", "commit", "-m", "factory reset: clean state before history purge"],
                        cwd=str(root), capture_output=True, text=True, timeout=30,
                    )

                # Save remote URLs before filter-repo wipes them
                remote_urls = {}
                remote_result = _sp.run(
                    ["git", "remote", "-v"],
                    cwd=str(root), capture_output=True, text=True, timeout=10,
                )
                for line in remote_result.stdout.strip().splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and "(push)" in line:
                        remote_urls[parts[0]] = parts[1]
                    elif len(parts) >= 2 and parts[0] not in remote_urls:
                        remote_urls[parts[0]] = parts[1]

                if remote_urls:
                    click.echo(f"    Saved {len(remote_urls)} remote(s): {', '.join(remote_urls.keys())}")
                else:
                    click.secho("    ⚠️  No remotes found — nothing to restore after purge", fg="yellow")

                # Run git filter-repo
                click.echo("    Running git filter-repo (this may take a while)...")
                filter_result = _sp.run(
                    [
                        "git", "filter-repo",
                        "--invert-paths",
                        "--path", "content/media/",
                        "--force",
                    ],
                    cwd=str(root), capture_output=True, text=True, timeout=300,
                )
                if filter_result.returncode != 0:
                    click.secho(
                        f"  ❌ git filter-repo failed: {filter_result.stderr.strip()}",
                        fg="red",
                    )
                else:
                    click.secho("  ✅ Media purged from git history", fg="green")

                    # Determine mirror mode BEFORE restoring remotes
                    mirror_reset_mode = os.environ.get("MIRROR_RESET_MODE", "leader")

                    # Re-add remotes — but skip mirror remotes in isolated mode
                    mirror_remote_names = set()
                    if mirror_reset_mode == "isolated":
                        # Figure out which remotes are mirrors so we can skip them
                        from ..mirror.manager import MirrorManager
                        try:
                            mm = MirrorManager(root)
                            mirror_remote_names = {m.id for m in mm.list_mirrors()}
                        except Exception:
                            pass  # No mirrors configured

                    for name, url in remote_urls.items():
                        if name in mirror_remote_names:
                            click.echo(f"    Skipped mirror remote: {name} (isolated mode)")
                            continue
                        _sp.run(
                            ["git", "remote", "add", name, url],
                            cwd=str(root), capture_output=True, text=True, timeout=10,
                        )
                        # Mask credentials in URLs for display
                        import re
                        safe_url = re.sub(r'://[^@]+@', '://***@', url)
                        click.echo(f"    Restored remote: {name} → {safe_url}")

                    # Auto force-push to origin
                    if "origin" in remote_urls:
                        click.echo("    Force-pushing to origin...")
                        push_result = _sp.run(
                            ["git", "push", "--force", "origin", "main"],
                            cwd=str(root), capture_output=True, text=True, timeout=120,
                        )
                        if push_result.returncode == 0:
                            click.secho("  ✅ Force-pushed to origin", fg="green")
                            # Restore tracking branch (filter-repo strips it)
                            _sp.run(
                                ["git", "branch", "--set-upstream-to=origin/main", "main"],
                                cwd=str(root), capture_output=True, text=True, timeout=5,
                            )
                            click.echo("    Restored tracking: main → origin/main")
                        else:
                            click.secho(
                                f"  ❌ Force-push failed: {push_result.stderr.strip()}\n"
                                "     Run manually: git push --force origin main",
                                fg="red",
                            )
                    else:
                        click.secho(
                            "  ⚠️  No origin remote — skipping push. Re-add and force-push manually.",
                            fg="yellow",
                        )

                    # In leader mode, also force-push to all mirror remotes
                    if mirror_reset_mode == "leader":
                        for name, url in remote_urls.items():
                            if name == "origin":
                                continue  # Already pushed
                            click.echo(f"    Force-pushing to mirror: {name}...")
                            push_result = _sp.run(
                                ["git", "push", "--force", name, "main"],
                                cwd=str(root), capture_output=True, text=True, timeout=120,
                            )
                            if push_result.returncode == 0:
                                click.secho(f"  ✅ Force-pushed to {name}", fg="green")
                            else:
                                click.secho(
                                    f"  ⚠️  Force-push to {name} failed: {push_result.stderr.strip()}",
                                    fg="yellow",
                                )

        # ── Mirror cascade protection ─────────────────────────────
        #    When MIRROR_RESET_MODE is 'isolated', disable mirroring
        #    entirely so no future sync can propagate the reset to
        #    the mirror. The mirror keeps running independently.
        #    User must re-enable MIRROR_ENABLED=true when ready.
        #    Default is 'leader' — reset propagates to mirrors.
        mirror_reset_mode = os.environ.get("MIRROR_RESET_MODE", "leader")
        if mirror_reset_mode == "isolated":
            # Disable mirroring in .env
            env_path = root / ".env"
            if env_path.exists():
                lines = env_path.read_text().splitlines()
                new_lines = []
                found = False
                for line in lines:
                    if line.strip().startswith("MIRROR_ENABLED"):
                        new_lines.append("MIRROR_ENABLED=false")
                        found = True
                    else:
                        new_lines.append(line)
                if not found:
                    new_lines.append("MIRROR_ENABLED=false")
                env_path.write_text("\n".join(new_lines) + "\n")
            click.secho(
                "  🔒 Mirror disabled (isolated mode) — re-enable manually when ready",
                fg="yellow",
            )
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


@click.command()
@click.option("--overwrite", is_flag=True, help="Overwrite existing scaffold articles")
@click.pass_context
def scaffold(ctx: click.Context, overwrite: bool) -> None:
    """Regenerate default articles (How It Works, Full Disclosure Statement).

    By default, only creates articles that don't already exist.
    Use --overwrite to replace existing ones.
    """
    from ..content.scaffold import generate_scaffold

    root = ctx.obj["root"]
    result = generate_scaffold(root, overwrite=overwrite)

    for slug in result["created"]:
        click.secho(f"  ✅ Created: {slug}", fg="green")
    for slug in result["skipped"]:
        click.echo(f"  ⏭️  Skipped: {slug} (already exists)")

    total = len(result["created"])
    if total:
        click.secho(f"\n📄 {total} scaffold article(s) created", fg="green")
    else:
        click.echo("\n📄 No articles created (all exist already)")
