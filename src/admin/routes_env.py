"""
Admin API — Environment file and secrets push endpoints.

Blueprint: env_bp
Prefix: /api
Routes:
    /api/env/read
    /api/env/write
    /api/secrets/push
"""

from __future__ import annotations

import subprocess

from flask import Blueprint, current_app, jsonify, request

from .helpers import gh_repo_flag, trigger_mirror_sync_bg

env_bp = Blueprint("env", __name__)


def _project_root():
    return current_app.config["PROJECT_ROOT"]


@env_bp.route("/env/read")
def api_env_read():
    """Read values from .env file."""
    env_file = _project_root() / ".env"
    values = {}

    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    # Remove quotes if present
                    value = value.strip().strip('"').strip("'")
                    values[key.strip()] = value

    return jsonify({"values": values})


@env_bp.route("/env/write", methods=["POST"])
def api_env_write():
    """Write values to .env file."""
    project_root = _project_root()
    data = request.json or {}
    secrets = data.get("secrets", {})

    if not secrets:
        return jsonify({"error": "No secrets provided"}), 400

    env_file = project_root / ".env"

    # Read existing .env
    existing = {}
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    existing[key.strip()] = value.strip()

    # Update with new values
    for name, value in secrets.items():
        if value:  # Only update if value is not empty
            existing[name] = f'"{value}"' if " " in value or "=" in value else value

    # Write back
    with open(env_file, "w") as f:
        for key, value in sorted(existing.items()):
            f.write(f"{key}={value}\n")

    return jsonify({
        "success": True,
        "updated": list(secrets.keys()),
    })


@env_bp.route("/secrets/push", methods=["POST"])
def api_push_secrets():
    """Push secrets/variables to GitHub AND save to .env file.

    Request body:
        secrets: dict of name->value for GitHub secrets (gh secret set)
        variables: dict of name->value for GitHub variables (gh variable set)
        env_values: dict of name->value for .env saving (all values)
        deletions: list of names to delete from .env
        push_to_github: bool
        save_to_env: bool
        exclude_from_github: list of names to skip for GitHub push
    """
    project_root = _project_root()
    data = request.json or {}
    secrets = data.get("secrets", {})
    variables = data.get("variables", {})
    env_values = data.get("env_values", {})
    deletions = data.get("deletions", [])
    push_to_github = data.get("push_to_github", True)
    save_to_env = data.get("save_to_env", True)
    exclude_from_github = set(data.get("exclude_from_github", []))

    # For .env saving: use env_values if provided, otherwise fall back to secrets+variables
    all_values = env_values if env_values else {**secrets, **variables}
    results = []
    deletions_applied = []

    # First, save to .env file
    if save_to_env and (all_values or deletions):
        env_file = project_root / ".env"
        existing = {}
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        existing[key.strip()] = value.strip()

        for name, value in all_values.items():
            if value:
                existing[name] = f'"{value}"' if " " in value or "=" in value else value

        # Apply deletions
        for name in deletions:
            if name in existing:
                del existing[name]
                deletions_applied.append(name)

        with open(env_file, "w") as f:
            for key, value in sorted(existing.items()):
                f.write(f"{key}={value}\n")

        # If PROJECT_NAME was updated, also patch state/current.json so the
        # change is reflected immediately on the dashboard and published site
        # (otherwise it only takes effect on the next tick or factory reset).
        new_project_name = all_values.get("PROJECT_NAME", "")
        if new_project_name:
            import json
            state_file = project_root / "state" / "current.json"
            if state_file.exists():
                try:
                    state_data = json.loads(state_file.read_text())
                    old_name = state_data.get("meta", {}).get("project", "")
                    if old_name != new_project_name:
                        state_data.setdefault("meta", {})["project"] = new_project_name
                        state_file.write_text(
                            json.dumps(state_data, indent=2, default=str)
                        )
                except Exception:
                    pass  # Non-critical — tick will sync it later

    # Then push to GitHub if requested
    if push_to_github:
        from ..config.system_status import check_tool
        gh_status = check_tool("gh")

        if not gh_status.installed:
            return jsonify({
                "env_saved": save_to_env,
                "github_error": "gh CLI not installed",
                "install_hint": gh_status.install_hint,
                "results": [],
                "all_success": False,
            })

        if not gh_status.authenticated:
            return jsonify({
                "env_saved": save_to_env,
                "github_error": "gh CLI not authenticated. Run: gh auth login",
                "results": [],
                "all_success": False,
            })

        # Push secrets via gh secret set
        repo_flag = gh_repo_flag(project_root)
        for name, value in secrets.items():
            if not value:
                continue
            if name.startswith("GITHUB_") or name in exclude_from_github:
                continue
            try:
                result = subprocess.run(
                    ["gh", "secret", "set", name, "--body", value] + repo_flag,
                    cwd=str(project_root),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                results.append({
                    "name": name,
                    "kind": "secret",
                    "success": result.returncode == 0,
                    "error": result.stderr if result.returncode != 0 else None,
                })
            except Exception as e:
                results.append({
                    "name": name, "kind": "secret",
                    "success": False, "error": str(e),
                })

        # Push variables via gh variable set
        for name, value in variables.items():
            if not value:
                continue
            if name in exclude_from_github:
                continue
            try:
                result = subprocess.run(
                    ["gh", "variable", "set", name, "--body", value] + repo_flag,
                    cwd=str(project_root),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                results.append({
                    "name": name,
                    "kind": "variable",
                    "success": result.returncode == 0,
                    "error": result.stderr if result.returncode != 0 else None,
                })
            except Exception as e:
                results.append({
                    "name": name, "kind": "variable",
                    "success": False, "error": str(e),
                })

    all_ok = all(r["success"] for r in results) if results else True

    # Auto-sync secrets to mirror if enabled and push succeeded
    if push_to_github and all_ok and results:
        trigger_mirror_sync_bg(project_root, "secrets-only")

    # ── DEPLOY_MODE → enable/disable GitHub workflows ──────────────
    workflow_results = []
    pages_result = None
    deploy_mode = all_values.get("DEPLOY_MODE", "").strip().lower()
    if deploy_mode in ("docker", "github-pages"):
        from ..config.system_status import check_tool
        gh_status = check_tool("gh")

        if gh_status.installed and gh_status.authenticated:
            repo_flag = gh_repo_flag(project_root)
            # docker → disable pipelines; github-pages → enable them
            action = "disable" if deploy_mode == "docker" else "enable"
            for wf in ("cron.yml", "deploy-site.yml"):
                try:
                    result = subprocess.run(
                        ["gh", "workflow", action, wf] + repo_flag,
                        cwd=str(project_root),
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    workflow_results.append({
                        "workflow": wf,
                        "action": action,
                        "success": result.returncode == 0,
                        "error": result.stderr.strip() if result.returncode != 0 else None,
                    })
                except Exception as e:
                    workflow_results.append({
                        "workflow": wf,
                        "action": action,
                        "success": False,
                        "error": str(e),
                    })

            # Auto-enable GitHub Pages (build_type=workflow) when mode is github-pages
            if deploy_mode == "github-pages":
                try:
                    # First try PUT (update existing Pages config)
                    result = subprocess.run(
                        ["gh", "api", "-X", "PUT",
                         "repos/{owner}/{repo}/pages",
                         "-f", "build_type=workflow"] + repo_flag,
                        cwd=str(project_root),
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if result.returncode != 0 and "Not Found" in (result.stderr + result.stdout):
                        # Pages not yet enabled — create it
                        result = subprocess.run(
                            ["gh", "api", "-X", "POST",
                             "repos/{owner}/{repo}/pages",
                             "-f", "build_type=workflow",
                             "-f", "source[branch]=main",
                             "-f", "source[path]=/"] + repo_flag,
                            cwd=str(project_root),
                            capture_output=True,
                            text=True,
                            timeout=15,
                        )
                    pages_result = {
                        "action": "enable",
                        "success": result.returncode == 0,
                        "error": result.stderr.strip() if result.returncode != 0 else None,
                    }
                except Exception as e:
                    pages_result = {
                        "action": "enable",
                        "success": False,
                        "error": str(e),
                    }

    return jsonify({
        "env_saved": save_to_env,
        "deletions_applied": deletions_applied,
        "results": results,
        "workflow_results": workflow_results,
        "pages_result": pages_result,
        "all_success": all_ok,
    })
