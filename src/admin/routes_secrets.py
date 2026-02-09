"""
Admin API — GitHub CLI and secrets management endpoints.

Blueprint: secrets_bp
Prefix: /api
Routes:
    /api/gh/status
    /api/gh/auto
    /api/gh/secrets
    /api/gh/install
    /api/secret/set
    /api/secret/remove
"""

from __future__ import annotations

import subprocess

from flask import Blueprint, current_app, jsonify, request

from .helpers import fresh_env, gh_repo_flag

secrets_bp = Blueprint("secrets", __name__)


def _project_root():
    return current_app.config["PROJECT_ROOT"]


def _env():
    return fresh_env(_project_root())


def _repo_flag():
    return gh_repo_flag(_project_root())


@secrets_bp.route("/gh/status")
def api_gh_status():
    """Get gh CLI status."""
    from ..config.system_status import check_tool
    status = check_tool("gh")
    return jsonify(status.to_dict())


@secrets_bp.route("/gh/auto")
def api_gh_auto():
    """Get GitHub token from gh CLI and detect repo from git remote."""
    project_root = _project_root()
    result = {"token": None, "repo": None}

    # Try to get token from gh auth token
    try:
        token_result = subprocess.run(
            ["gh", "auth", "token"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if token_result.returncode == 0 and token_result.stdout.strip():
            result["token"] = token_result.stdout.strip()
    except Exception:
        pass

    # Try to detect repo from git remote
    try:
        remote_result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if remote_result.returncode == 0 and remote_result.stdout.strip():
            url = remote_result.stdout.strip()
            # Parse owner/repo from URL
            # Formats: git@github.com:owner/repo.git or https://github.com/owner/repo.git
            import re
            match = re.search(r'github\.com[:/]([^/]+/[^/\s]+?)(?:\.git)?$', url)
            if match:
                result["repo"] = match.group(1)
    except Exception:
        pass

    return jsonify(result)


@secrets_bp.route("/gh/secrets")
def api_gh_secrets():
    """Get list of secrets AND variables set in GitHub repo."""
    project_root = _project_root()
    try:
        # Check if gh is installed and authenticated
        from ..config.system_status import check_tool
        gh_status = check_tool("gh")

        if not gh_status.installed:
            return jsonify({
                "available": False,
                "reason": "gh CLI not installed",
                "secrets": [],
                "variables": [],
            })

        if not gh_status.authenticated:
            return jsonify({
                "available": False,
                "reason": "gh CLI not authenticated",
                "secrets": [],
                "variables": [],
            })

        repo_flag = _repo_flag()

        # Get list of secrets from GitHub
        result = subprocess.run(
            ["gh", "secret", "list"] + repo_flag,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=15,
        )

        secret_names = []
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    if parts:
                        secret_names.append(parts[0])

        # Get list of variables from GitHub
        var_result = subprocess.run(
            ["gh", "variable", "list"] + repo_flag,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=15,
        )

        variable_names = []
        if var_result.returncode == 0:
            for line in var_result.stdout.strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    if parts:
                        variable_names.append(parts[0])

        return jsonify({
            "available": True,
            "secrets": secret_names,
            "variables": variable_names,
        })

    except Exception as e:
        return jsonify({
            "available": False,
            "reason": str(e),
            "secrets": [],
            "variables": [],
        })


@secrets_bp.route("/secret/set", methods=["POST"])
def api_secret_set():
    """Set a single secret to .env and/or GitHub."""
    project_root = _project_root()
    data = request.json or {}
    name = data.get("name")
    value = data.get("value")
    target = data.get("target", "both")  # "local", "github", or "both"

    if not name:
        return jsonify({"error": "Secret name required"}), 400

    results = {"name": name, "local": None, "github": None}

    # Save to .env
    if target in ("local", "both") and value:
        try:
            env_file = project_root / ".env"
            existing = {}
            if env_file.exists():
                with open(env_file) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, val = line.partition("=")
                            existing[key.strip()] = val.strip()

            existing[name] = f'"{value}"' if " " in value or "=" in value else value

            with open(env_file, "w") as f:
                for key, val in sorted(existing.items()):
                    f.write(f"{key}={val}\n")

            results["local"] = {"success": True}
        except Exception as e:
            results["local"] = {"success": False, "error": str(e)}

    # Push to GitHub
    if target in ("github", "both") and value:
        repo_flag = _repo_flag()
        try:
            result = subprocess.run(
                ["gh", "secret", "set", name] + repo_flag,
                input=value,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=15,
            )
            results["github"] = {
                "success": result.returncode == 0,
                "error": result.stderr if result.returncode != 0 else None,
            }
        except Exception as e:
            results["github"] = {"success": False, "error": str(e)}

    return jsonify(results)


@secrets_bp.route("/secret/remove", methods=["POST"])
def api_secret_remove():
    """Remove a secret/variable from .env and/or GitHub."""
    project_root = _project_root()
    data = request.json or {}
    name = data.get("name")
    target = data.get("target", "both")  # "local", "github", or "both"
    kind = data.get("kind", "secret")    # "secret" or "variable"

    if not name:
        return jsonify({"error": "Secret name required"}), 400

    results = {"name": name, "local": None, "github": None}

    # Remove from .env
    if target in ("local", "both"):
        try:
            env_file = project_root / ".env"
            if env_file.exists():
                lines = []
                with open(env_file) as f:
                    for line in f:
                        if not line.strip().startswith(f"{name}="):
                            lines.append(line)
                with open(env_file, "w") as f:
                    f.writelines(lines)
                results["local"] = {"success": True}
            else:
                results["local"] = {"success": True, "note": "File not found"}
        except Exception as e:
            results["local"] = {"success": False, "error": str(e)}

    # Remove from GitHub
    if target in ("github", "both"):
        # Use correct gh command based on kind
        gh_cmd = "variable" if kind == "variable" else "secret"
        repo_flag = _repo_flag()
        try:
            result = subprocess.run(
                ["gh", gh_cmd, "delete", name] + repo_flag,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=15,
            )
            results["github"] = {
                "success": result.returncode == 0,
                "error": result.stderr if result.returncode != 0 else None,
            }
        except Exception as e:
            results["github"] = {"success": False, "error": str(e)}

    return jsonify(results)


@secrets_bp.route("/gh/install", methods=["POST"])
def api_gh_install():
    """Spawn terminal to install gh CLI (user can enter sudo password)."""
    import platform

    project_root = _project_root()
    system = platform.system().lower()

    if system == "linux":
        # Full install command
        install_script = '''#!/bin/bash
echo "Installing GitHub CLI..."
(type -p wget >/dev/null || (sudo apt update && sudo apt install wget -y)) \\
    && sudo mkdir -p -m 755 /etc/apt/keyrings \\
    && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \\
    && cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \\
    && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \\
    && sudo mkdir -p -m 755 /etc/apt/sources.list.d \\
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \\
    && sudo apt update \\
    && sudo apt install gh -y

if command -v gh &>/dev/null; then
    echo ""
    echo "✓ GitHub CLI installed successfully!"
    gh --version
    echo ""
    echo "Next step: Run 'gh auth login' to authenticate"
else
    echo ""
    echo "✗ Installation failed"
fi
echo ""
read -p "Press Enter to close..."
'''
        # Write script to temp file
        script_path = project_root / "state" / ".install_gh.sh"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        with open(script_path, "w") as f:
            f.write(install_script)
        script_path.chmod(0o755)

        # Try to open in a terminal
        terminal_cmds = [
            ["gnome-terminal", "--", "bash", str(script_path)],
            ["xterm", "-e", f"bash {script_path}"],
            ["konsole", "-e", f"bash {script_path}"],
            ["x-terminal-emulator", "-e", f"bash {script_path}"],
        ]

        for cmd in terminal_cmds:
            try:
                subprocess.Popen(cmd, start_new_session=True)
                return jsonify({
                    "success": True,
                    "message": "Terminal opened. Enter your sudo password to install.",
                })
            except FileNotFoundError:
                continue

        # Fallback: return the command
        return jsonify({
            "success": False,
            "fallback": True,
            "command": install_script,
            "message": "Could not open terminal. Run this in your terminal:",
        })

    elif system == "darwin":
        # macOS - try Terminal.app
        try:
            subprocess.Popen([
                "osascript", "-e",
                'tell application "Terminal" to do script "brew install gh && gh auth login"'
            ])
            return jsonify({
                "success": True,
                "message": "Terminal opened with install command.",
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "command": "brew install gh && gh auth login",
                "message": str(e),
            })

    return jsonify({
        "success": False,
        "message": "Unsupported OS",
        "command": "# Visit https://cli.github.com/",
    })


@secrets_bp.route("/sentinel/setup", methods=["POST"])
def api_sentinel_setup():
    """Spawn terminal to run the Sentinel Worker setup script."""
    project_root = _project_root()
    script_path = project_root / "scripts" / "setup-sentinel.sh"

    if not script_path.exists():
        return jsonify({
            "success": False,
            "message": "scripts/setup-sentinel.sh not found",
        }), 404

    # Check if auto-run mode requested
    data = request.json or {}
    auto_run = data.get("autoRun", False)
    y_flag = " -y" if auto_run else ""

    # Wrap the script — in auto mode, close immediately; interactive keeps open
    if auto_run:
        wrapper = f'bash {script_path}{y_flag}'
    else:
        wrapper = f'bash {script_path}; echo ""; read -p "Press Enter to close…"'

    # Try to open in a terminal
    terminal_cmds = [
        ["gnome-terminal", "--", "bash", "-c", wrapper],
        ["xterm", "-e", f"bash -c '{wrapper}'"],
        ["konsole", "-e", f"bash -c '{wrapper}'"],
        ["x-terminal-emulator", "-e", f"bash -c '{wrapper}'"],
    ]

    for cmd in terminal_cmds:
        try:
            subprocess.Popen(cmd, cwd=str(project_root), start_new_session=True)
            return jsonify({
                "success": True,
                "message": "Terminal opened. The setup script will walk you through deploying the Sentinel Worker.",
            })
        except FileNotFoundError:
            continue

    # Fallback: return the command
    return jsonify({
        "success": False,
        "fallback": True,
        "command": "./scripts/setup-sentinel.sh",
        "message": "Could not open terminal. Run this in your terminal:",
    })


@secrets_bp.route("/sentinel/setup-status")
def api_sentinel_setup_status():
    """Check sentinel setup progress via signal file."""
    project_root = _project_root()
    signal_file = project_root / ".sentinel-setup-result"

    if not signal_file.exists():
        return jsonify({"status": "unknown"})

    try:
        import json as _json
        data = _json.loads(signal_file.read_text())
        return jsonify(data)
    except Exception:
        return jsonify({"status": "unknown"})
