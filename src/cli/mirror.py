"""
CLI mirror commands — status, sync, and cleanup of GitHub mirror repos.

Usage:
    python -m src.main mirror-status [--json]
    python -m src.main mirror-sync [--code-only] [--secrets-only] [--vars-only]
    python -m src.main mirror-clean [--code] [--secrets] [--variables] [--all]
"""

from __future__ import annotations

import os

import click


@click.command("mirror-status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON (for API)")
@click.pass_context
def mirror_status(ctx: click.Context, as_json: bool) -> None:
    """Show mirror configuration and sync status."""
    import json as json_lib

    from ..mirror.config import MirrorSettings
    from ..mirror.state import MirrorState

    settings = MirrorSettings.from_env()
    state = MirrorState.load()

    # Merge config + state: always show configured mirrors
    mirrors = []
    for mirror in settings.mirrors:
        slave = state.get_slave(mirror.id)
        entry = {
            "id": mirror.id,
            "repo": mirror.repo,
            "type": mirror.type,
            "enabled": mirror.enabled,
        }
        if slave:
            from dataclasses import asdict
            entry["code"] = asdict(slave.code)
            entry["secrets"] = asdict(slave.secrets)
            entry["variables"] = asdict(slave.variables)
            entry["workflows"] = asdict(slave.workflows)
            entry["health"] = slave.health

            # Staleness detection: compare stored fingerprint vs current env
            from ..mirror.github_sync import secrets_fingerprint, variables_fingerprint
            mirror_num = mirror.id.replace("mirror-", "")
            if slave.secrets.status == "ok" and slave.secrets.fingerprint:
                current_fp = secrets_fingerprint(mirror_num)
                if current_fp != slave.secrets.fingerprint:
                    entry["secrets"]["status"] = "stale"
                    entry["secrets"]["detail"] = f"{slave.secrets.detail} (env changed)"
            if slave.variables.status == "ok" and slave.variables.fingerprint:
                current_fp = variables_fingerprint()
                if current_fp != slave.variables.fingerprint:
                    entry["variables"]["status"] = "stale"
                    entry["variables"]["detail"] = f"{slave.variables.detail} (env changed)"
        else:
            entry["code"] = {"status": "never", "last_sync_iso": None, "last_error": None, "detail": None, "fingerprint": None}
            entry["secrets"] = {"status": "never", "last_sync_iso": None, "last_error": None, "detail": None, "fingerprint": None}
            entry["variables"] = {"status": "never", "last_sync_iso": None, "last_error": None, "detail": None, "fingerprint": None}
            entry["workflows"] = {"status": "never", "last_sync_iso": None, "last_error": None, "detail": None, "fingerprint": None}
            entry["health"] = "unknown"
        mirrors.append(entry)

    result = {
        "enabled": settings.enabled and len(settings.mirrors) > 0,
        "self_role": state.self_role,
        "mirrors_configured": len(settings.mirrors),
        "last_full_sync_iso": state.last_full_sync_iso,
        "mirrors": mirrors,
    }

    if as_json:
        click.echo(json_lib.dumps(result, indent=2, default=str))
        return

    # Human-readable output
    click.echo("\n🔀 Mirror Status\n")
    click.echo(f"  Enabled:    {'Yes' if result['enabled'] else 'No'}")
    click.echo(f"  Role:       {state.self_role}")
    click.echo(f"  Mirrors:    {len(mirrors)} configured")
    if state.last_full_sync_iso:
        click.echo(f"  Last sync:  {state.last_full_sync_iso}")
    click.echo()

    if not mirrors:
        click.echo("  No mirrors configured.")
        click.echo("  Set MIRROR_ENABLED=true, MIRROR_1_REPO, MIRROR_1_TOKEN in .env")
        click.echo()
        return

    for m in mirrors:
        click.echo(f"  📦 {m['repo']} ({m['id']})")
        for layer in ("code", "secrets", "variables"):
            layer_data = m[layer]
            status = layer_data.get("status", "unknown")
            icon = {"ok": "✅", "failed": "❌", "stale": "⚠️", "never": "⏳", "unknown": "⏳"}.get(status, "❓")
            line = f"    {icon} {layer}: {status}"
            if layer_data.get("detail"):
                line += f" ({layer_data['detail']})"
            if layer_data.get("last_error"):
                line += f" — {layer_data['last_error'][:80]}"
            if layer_data.get("last_sync_iso"):
                line += f" [{layer_data['last_sync_iso'][:19]}]"
            click.echo(line)
        click.echo()


@click.command("mirror-sync")
@click.option("--code-only", is_flag=True, help="Only sync code (git push)")
@click.option("--secrets-only", is_flag=True, help="Only sync secrets")
@click.option("--vars-only", is_flag=True, help="Only sync variables")
@click.option("--json-lines", "jsonl", is_flag=True, help="Output JSON lines for SSE streaming")
@click.pass_context
def mirror_sync(ctx: click.Context, code_only: bool, secrets_only: bool, vars_only: bool, jsonl: bool) -> None:
    """Run mirror sync operations with real-time progress."""
    import json as _json

    from ..mirror.manager import MirrorManager

    def emit(data: dict):
        """Output a JSON line and flush immediately for streaming."""
        if jsonl:
            print(_json.dumps(data), flush=True)
        else:
            step = data.get("step", "")
            status = data.get("status", "")
            detail = data.get("detail", "")
            progress = data.get("progress", "")
            error = data.get("error", "")
            if status == "start":
                click.echo(f"\n🔀 {detail}")
            elif status == "mirror_start":
                click.echo(f"\n  ─── {detail} ───")
            elif status == "running":
                pass  # suppress in human mode
            elif status == "progress":
                icon = "✅" if data.get("ok") else "❌"
                click.echo(f"    {icon} {detail} ({progress})")
            elif status == "ok":
                click.secho(f"    ✅ {step}: {progress} {detail}", fg="green")
            elif status == "failed":
                click.secho(f"    ❌ {step}: {progress} — {error}", fg="red")
            elif status == "done":
                if data.get("success"):
                    click.secho("\n✅ Mirror sync complete", fg="green")
                else:
                    click.secho(f"\n⚠️  Finished with {data.get('errors', 0)} error(s)", fg="yellow")

    root = ctx.obj["root"]
    mm = MirrorManager.from_env()

    if not mm.enabled:
        emit({"step": "init", "status": "failed", "error": "Mirror not enabled. Set MIRROR_ENABLED=true"})
        raise SystemExit(1)

    mirrors = mm.settings.get_all_enabled()
    emit({"step": "init", "status": "start", "detail": f"Syncing {len(mirrors)} mirror(s)...", "count": len(mirrors)})

    sync_all = not (code_only or secrets_only or vars_only)
    master_repo = os.environ.get("GITHUB_REPOSITORY")
    errors = 0

    # Load state for persistence
    from ..mirror.state import MirrorState
    state = MirrorState.load()

    for mirror in mirrors:
        emit({"step": "mirror", "status": "mirror_start", "detail": mirror.repo or mirror.id, "mirror_id": mirror.id})
        slave = state.ensure_slave(mirror.id, mirror.type, mirror.repo, mirror.url)

        # --- CODE ---
        if sync_all or code_only:
            emit({"step": "code", "status": "running", "mirror_id": mirror.id})
            from ..mirror import git_sync
            ok, commit, error = git_sync.push_to_mirror(mirror, root, "main", force=True)
            if ok:
                slave.code.mark_ok(detail=commit)
                emit({"step": "code", "status": "ok", "detail": commit or "up-to-date", "mirror_id": mirror.id})
            else:
                slave.code.mark_failed(error or "Unknown error")
                emit({"step": "code", "status": "failed", "error": error, "mirror_id": mirror.id})
                errors += 1
            state.save()

        # --- SECRETS ---
        if sync_all or secrets_only:
            from ..mirror.github_sync import (
                RENAMED_SECRETS,
                SYNCABLE_SECRETS,
                secrets_fingerprint,
                sync_secret,
            )
            synced = 0
            secret_errors = []

            # Standard secrets (same name on master and slave)
            eligible = [(s, s, os.environ.get(s)) for s in SYNCABLE_SECRETS if os.environ.get(s)]

            # Per-mirror renamed secrets (e.g. MIRROR_1_RENEWAL_TRIGGER_TOKEN → RENEWAL_TRIGGER_TOKEN)
            mirror_num = mirror.id.replace("mirror-", "")  # "mirror-1" → "1"
            for master_key_template, slave_key in RENAMED_SECRETS.items():
                master_key = master_key_template.replace("{N}", mirror_num)
                value = os.environ.get(master_key)
                if value:
                    eligible.append((master_key, slave_key, value))

            total = len(eligible)
            emit({"step": "secrets", "status": "running", "progress": f"0/{total}", "mirror_id": mirror.id})

            for master_name, slave_name, value in eligible:
                ok, err = sync_secret(mirror.token, mirror.repo, slave_name, value)
                if ok:
                    synced += 1
                else:
                    secret_errors.append(f"{slave_name}: {err}")
                emit({"step": "secrets", "status": "progress", "progress": f"{synced}/{total}",
                      "detail": slave_name, "ok": ok, "mirror_id": mirror.id})

            if synced == total:
                slave.secrets.mark_ok(detail=f"{synced}/{total}", fingerprint=secrets_fingerprint(mirror_num))
                emit({"step": "secrets", "status": "ok", "progress": f"{synced}/{total}", "mirror_id": mirror.id})
            else:
                slave.secrets.mark_failed("; ".join(secret_errors))
                emit({"step": "secrets", "status": "failed", "progress": f"{synced}/{total}",
                      "error": "; ".join(secret_errors), "mirror_id": mirror.id})
                errors += 1
            state.save()

        # --- VARIABLES ---
        if sync_all or vars_only:
            from ..mirror.github_sync import sync_variable, variables_fingerprint
            vars_to_sync = {
                "MIRROR_ROLE": "SLAVE",
                "SENTINEL_THRESHOLD": os.environ.get("SENTINEL_THRESHOLD", "3"),
                "ADAPTER_MOCK_MODE": "true",
            }
            if os.environ.get("ARCHIVE_ENABLED"):
                vars_to_sync["ARCHIVE_ENABLED"] = os.environ["ARCHIVE_ENABLED"]
            if os.environ.get("ARCHIVE_URL"):
                vars_to_sync["ARCHIVE_URL"] = os.environ["ARCHIVE_URL"]
            if master_repo:
                vars_to_sync["MASTER_REPO"] = master_repo

            total = len(vars_to_sync)
            synced = 0
            var_errors = []
            emit({"step": "variables", "status": "running", "progress": f"0/{total}", "mirror_id": mirror.id})

            for var_name, var_value in vars_to_sync.items():
                ok, err = sync_variable(mirror.token, mirror.repo, var_name, var_value)
                if ok:
                    synced += 1
                else:
                    var_errors.append(f"{var_name}: {err}")
                emit({"step": "variables", "status": "progress", "progress": f"{synced}/{total}",
                      "detail": var_name, "ok": ok, "mirror_id": mirror.id})

            if synced == total:
                slave.variables.mark_ok(detail=f"{synced}/{total}", fingerprint=variables_fingerprint())
                emit({"step": "variables", "status": "ok", "progress": f"{synced}/{total}", "mirror_id": mirror.id})
            else:
                slave.variables.mark_failed("; ".join(var_errors))
                emit({"step": "variables", "status": "failed", "progress": f"{synced}/{total}",
                      "error": "; ".join(var_errors), "mirror_id": mirror.id})
                errors += 1
            state.save()

    emit({"step": "done", "status": "done", "success": errors == 0, "errors": errors})


@click.command("mirror-clean")
@click.option("--code", "clean_code", is_flag=True, help="Reset mirror repo to empty (wipe all code)")
@click.option("--secrets", "clean_secrets", is_flag=True, help="Delete all secrets from mirror")
@click.option("--variables", "clean_vars", is_flag=True, help="Delete all variables from mirror")
@click.option("--all", "clean_all", is_flag=True, help="Clean EVERYTHING: code + secrets + variables")
@click.option("--json-lines", "jsonl", is_flag=True, help="Output JSON lines for SSE streaming")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def mirror_clean(ctx: click.Context, clean_code: bool, clean_secrets: bool, clean_vars: bool, clean_all: bool, jsonl: bool, yes: bool) -> None:
    """Clean synced code/secrets/variables from mirror repos.

    SAFETY: This ONLY targets mirror repos (MIRROR_1_REPO etc.),
    NEVER the master repo (GITHUB_REPOSITORY). Hardcoded protection.
    """
    import json as _json
    import subprocess
    import tempfile

    from ..mirror.config import MirrorSettings

    def emit(data: dict):
        if jsonl:
            print(_json.dumps(data), flush=True)
        else:
            status = data.get("status", "")
            detail = data.get("detail", "")
            error = data.get("error", "")
            if status == "start":
                click.echo(f"  🗑️  {detail}")
            elif status == "running":
                click.echo(f"  ⏳ {detail}")
            elif status == "ok":
                click.secho(f"  ✅ {detail}", fg="green")
            elif status == "failed":
                click.secho(f"  ❌ {detail}: {error}", fg="red")

    settings = MirrorSettings.from_env()
    mirrors = settings.get_all_enabled()
    master_repo = os.environ.get("GITHUB_REPOSITORY", "")

    if not mirrors:
        emit({"step": "init", "status": "failed", "error": "No mirrors configured"})
        raise SystemExit(1)

    if clean_all:
        clean_code = True
        clean_secrets = True
        clean_vars = True
    if not clean_code and not clean_secrets and not clean_vars:
        if not jsonl:
            click.secho("Specify --code, --secrets, --variables, or --all", fg="yellow")
        raise SystemExit(1)

    # Load state to update after cleaning
    from ..mirror.state import MirrorState, SyncStatus
    state = MirrorState.load()

    for mirror in mirrors:
        # ⛔ HARDCODED SAFETY: NEVER clean the master repo
        if mirror.repo == master_repo:
            emit({"step": "safety", "status": "failed",
                  "error": f"REFUSED — {mirror.repo} is GITHUB_REPOSITORY (master)"})
            continue

        if not jsonl:
            click.echo(f"\n🗑️  Cleaning {mirror.repo}...")
        if not yes and not jsonl:
            click.confirm(f"Really clean {mirror.repo}?", abort=True)

        emit({"step": "clean_start", "status": "start", "detail": mirror.repo})

        env = {**os.environ, "GH_TOKEN": mirror.token}
        slave = state.ensure_slave(mirror.id, mirror.type, mirror.repo, mirror.url)

        # --- CODE: force-push empty orphan to wipe all content ---
        if clean_code:
            emit({"step": "clean_code", "status": "running", "detail": "Wiping repo content..."})
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    subprocess.run(["git", "init", tmpdir], capture_output=True, text=True, check=True)
                    subprocess.run(["git", "-C", tmpdir, "checkout", "--orphan", "main"], capture_output=True, text=True, check=True)
                    subprocess.run(["git", "-C", tmpdir, "commit", "--allow-empty", "-m", "mirror cleaned"], capture_output=True, text=True, check=True)
                    push_url = f"https://x-access-token:{mirror.token}@github.com/{mirror.repo}.git"
                    result = subprocess.run(
                        ["git", "-C", tmpdir, "push", "--force", push_url, "main"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if result.returncode == 0:
                        emit({"step": "clean_code", "status": "ok", "detail": "Repo content wiped"})
                    else:
                        emit({"step": "clean_code", "status": "failed", "detail": "git push", "error": result.stderr.strip()})
            except Exception as e:
                emit({"step": "clean_code", "status": "failed", "detail": "code cleanup", "error": str(e)})
            slave.code = SyncStatus(status="unknown", detail="cleaned")
            state.save()

        # --- SECRETS: list what exists, delete those ---
        if clean_secrets:
            emit({"step": "clean_secrets", "status": "running", "detail": "Listing secrets..."})
            list_result = subprocess.run(
                ["gh", "secret", "list", "-R", mirror.repo, "--json", "name", "-q", ".[].name"],
                env=env, capture_output=True, text=True, timeout=15,
            )
            existing = [s.strip() for s in list_result.stdout.strip().split("\n") if s.strip()] if list_result.returncode == 0 and list_result.stdout.strip() else []

            if not existing:
                emit({"step": "clean_secrets", "status": "ok", "detail": "No secrets to delete"})
            else:
                emit({"step": "clean_secrets", "status": "running", "detail": f"Deleting {len(existing)} secret(s)..."})
                for name in existing:
                    r = subprocess.run(["gh", "secret", "delete", name, "-R", mirror.repo], env=env, capture_output=True, text=True, timeout=15)
                    if r.returncode == 0:
                        emit({"step": "clean_secret", "status": "ok", "detail": name})
                    else:
                        emit({"step": "clean_secret", "status": "failed", "detail": name, "error": r.stderr.strip()})
            slave.secrets = SyncStatus(status="unknown", detail="cleaned")
            state.save()

        # --- VARIABLES: list what exists, delete those ---
        if clean_vars:
            emit({"step": "clean_vars", "status": "running", "detail": "Listing variables..."})
            list_result = subprocess.run(
                ["gh", "variable", "list", "-R", mirror.repo, "--json", "name", "-q", ".[].name"],
                env=env, capture_output=True, text=True, timeout=15,
            )
            existing = [v.strip() for v in list_result.stdout.strip().split("\n") if v.strip()] if list_result.returncode == 0 and list_result.stdout.strip() else []

            if not existing:
                emit({"step": "clean_vars", "status": "ok", "detail": "No variables to delete"})
            else:
                emit({"step": "clean_vars", "status": "running", "detail": f"Deleting {len(existing)} variable(s)..."})
                for name in existing:
                    r = subprocess.run(["gh", "variable", "delete", name, "-R", mirror.repo], env=env, capture_output=True, text=True, timeout=15)
                    if r.returncode == 0:
                        emit({"step": "clean_var", "status": "ok", "detail": name})
                    else:
                        emit({"step": "clean_var", "status": "failed", "detail": name, "error": r.stderr.strip()})
            slave.variables = SyncStatus(status="unknown", detail="cleaned")
            state.save()

    emit({"step": "done", "status": "done", "success": True})
    if not jsonl:
        click.secho("\n✅ Mirror clean complete", fg="green")
