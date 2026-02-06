"""
Local Admin Server — Flask-based web interface.

This provides a simple web server for local management.
It should NEVER be exposed to the internet.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import webbrowser
from pathlib import Path
from threading import Timer
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template, request, send_from_directory

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Create the Flask application."""
    
    # Get paths
    project_root = Path(__file__).parent.parent.parent
    static_folder = Path(__file__).parent / "static"
    
    app = Flask(
        __name__,
        static_folder=str(static_folder),
        static_url_path="/static",
    )
    
    # Store project root for use in routes
    app.config["PROJECT_ROOT"] = project_root
    
    # Disable reloader warning
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    
    # ---------------------------------------------------------------------------
    # REQUEST LOGGING — log all API requests with timing
    # ---------------------------------------------------------------------------
    
    @app.before_request
    def log_request_start():
        """Record request start time."""
        import time
        request._start_time = time.time()
    
    @app.after_request
    def log_request_end(response):
        """Log request with duration for API endpoints."""
        import time
        duration_ms = 0
        if hasattr(request, '_start_time'):
            duration_ms = int((time.time() - request._start_time) * 1000)
        
        # Only log API calls (not static files)
        if request.path.startswith('/api/'):
            logger.info(
                f"{request.method} {request.path} → {response.status_code} ({duration_ms}ms)"
            )
        return response
    
    logger.info(f"Admin server initialized (project_root={project_root})")
    
    # ===========================================================================
    # ROUTES
    # ===========================================================================
    
    @app.route("/")
    def index():
        """Serve the admin dashboard."""
        index_path = static_folder / "index.html"
        if index_path.exists():
            return send_from_directory(str(static_folder), "index.html")
        return "Admin panel not found. Please ensure static/index.html exists.", 404
    
    @app.route("/api/status")
    def api_status():
        """Get comprehensive system status."""
        from ..config.system_status import get_system_status
        
        status = get_system_status(
            state_file=project_root / "state" / "current.json",
            policy_dir=project_root / "policy",
        )
        return jsonify(status.to_dict())
    
    @app.route("/api/run", methods=["POST"])
    def api_run():
        """Run a command."""
        data = request.json or {}
        command = data.get("command", "")
        
        allowed_commands = {
            "status": ["python", "-m", "src.main", "status"],
            "tick": ["python", "-m", "src.main", "tick"],
            "tick-dry": ["python", "-m", "src.main", "tick", "--dry-run"],
            "build-site": ["python", "-m", "src.main", "build-site"],
            "check-config": ["python", "-m", "src.main", "check-config"],
            "test-all": ["python", "-m", "src.main", "test", "all"],
            "health": ["python", "-m", "src.main", "health"],
            "config-status": ["python", "-m", "src.main", "config-status"],
            "explain": ["python", "-m", "src.main", "explain"],
            "simulate": ["python", "-m", "src.main", "simulate"],
            "retry-queue": ["python", "-m", "src.main", "retry-queue"],
            "circuit-breakers": ["python", "-m", "src.main", "circuit-breakers"],
            "test email": ["python", "-m", "src.main", "test", "email"],
            "test sms": ["python", "-m", "src.main", "test", "sms"],
        }
        
        if command not in allowed_commands:
            return jsonify({"error": f"Unknown command: {command}"}), 400
        
        try:
            result = subprocess.run(
                allowed_commands[command],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "TERM": "dumb"},  # Disable ANSI codes
            )
            return jsonify({
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr,
                "returncode": result.returncode,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Command timed out"}), 504
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/renew", methods=["POST"])
    def api_renew():
        """Renew the deadline."""
        data = request.json or {}
        hours = data.get("hours", 48)
        
        try:
            result = subprocess.run(
                ["python", "-m", "src.main", "renew", "--hours", str(hours)],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return jsonify({
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/state/set-deadline", methods=["POST"])
    def api_set_deadline():
        """Set the countdown deadline via CLI."""
        data = request.json or {}
        hours = data.get("hours")
        
        if hours is None:
            return jsonify({"success": False, "error": "Provide 'hours'"}), 400
        
        try:
            result = subprocess.run(
                ["python", "-m", "src.main", "set-deadline", "--hours", str(hours)],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return jsonify({
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else None,
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    
    @app.route("/api/archive", methods=["POST"])
    def api_archive():
        """
        Archive a URL to the Internet Archive's Wayback Machine.
        
        Request body:
        - url: Optional URL to archive (defaults to GitHub Pages URL)
        
        Returns:
        - success: bool
        - archive_url: The permanent Wayback Machine URL
        - original_url: The URL that was archived
        - error: Error message if failed
        """
        data = request.json or {}
        custom_url = data.get("url")
        
        logger.info(f"Archive request received. Custom URL: {custom_url}")
        
        try:
            from ..adapters.internet_archive import archive_url_now
            
            # Determine URL to archive
            if custom_url:
                url = custom_url
            else:
                # Try to get from environment
                archive_url = os.environ.get("ARCHIVE_URL")
                if archive_url:
                    url = archive_url
                else:
                    # Fall back to GitHub Pages
                    repo = os.environ.get("GITHUB_REPOSITORY")
                    if not repo:
                        # Try to detect from git
                        try:
                            result = subprocess.run(
                                ["git", "remote", "get-url", "origin"],
                                cwd=str(project_root),
                                capture_output=True,
                                text=True,
                                timeout=5,
                            )
                            if result.returncode == 0:
                                remote_url = result.stdout.strip()
                                import re
                                match = re.search(r"github\.com[:/]([^/]+/[^/.]+)", remote_url)
                                if match:
                                    repo = match.group(1)
                        except Exception:
                            pass
                    
                    if not repo:
                        return jsonify({
                            "success": False,
                            "error": "No URL to archive. Set ARCHIVE_URL, GITHUB_REPOSITORY, or provide a custom URL.",
                        }), 400
                    
                    parts = repo.split("/")
                    url = f"https://{parts[0]}.github.io/{parts[1]}/"
            
            logger.info(f"Archiving URL: {url}")
            logger.debug("Archive may take up to 3 minutes")
            
            # Archive the URL
            result = archive_url_now(url)
            
            logger.info(f"Archive result: success={result.get('success')}, url={result.get('archive_url', 'N/A')}")
            
            return jsonify(result)
            
        except Exception as e:
            import traceback
            logger.error(f"Archive exception: {e}", exc_info=True)
            return jsonify({
                "success": False,
                "error": str(e),
            }), 500
    
    @app.route("/api/archive/check", methods=["POST"])
    def api_archive_check():
        """
        Check if a URL is already archived on the Wayback Machine.
        
        Request body:
        - url: URL to check
        
        Returns:
        - archived: bool
        - snapshot: Latest snapshot info if archived
        """
        data = request.json or {}
        url = data.get("url")
        
        if not url:
            return jsonify({"error": "URL required"}), 400
        
        try:
            from ..adapters.internet_archive import InternetArchiveAdapter
            snapshot = InternetArchiveAdapter.check_availability(url)
            
            return jsonify({
                "archived": snapshot is not None,
                "snapshot": snapshot,
                "url": url,
            })
        except Exception as e:
            return jsonify({
                "archived": False,
                "error": str(e),
                "url": url,
            })
    
    @app.route("/api/env/read")
    def api_env_read():
        """Read values from .env file."""
        env_file = project_root / ".env"
        values = {}
        
        if env_file.exists():
            with open(env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        # Remove quotes if present
                        value = value.strip().strip('"').strip("'")
                        values[key.strip()] = value
        
        return jsonify({"values": values})
    
    @app.route("/api/env/write", methods=["POST"])
    def api_env_write():
        """Write values to .env file."""
        data = request.json or {}
        secrets = data.get("secrets", {})
        
        if not secrets:
            return jsonify({"error": "No secrets provided"}), 400
        
        env_file = project_root / ".env"
        
        # Read existing .env
        existing = {}
        if env_file.exists():
            with open(env_file, "r") as f:
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
    
    @app.route("/api/secrets/push", methods=["POST"])
    def api_push_secrets():
        """Push secrets to GitHub AND save to .env file."""
        data = request.json or {}
        secrets = data.get("secrets", {})
        push_to_github = data.get("push_to_github", True)
        save_to_env = data.get("save_to_env", True)
        
        results = []
        
        # First, save to .env file
        if save_to_env and secrets:
            env_file = project_root / ".env"
            existing = {}
            if env_file.exists():
                with open(env_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, value = line.partition("=")
                            existing[key.strip()] = value.strip()
            
            for name, value in secrets.items():
                if value:
                    existing[name] = f'"{value}"' if " " in value or "=" in value else value
            
            with open(env_file, "w") as f:
                for key, value in sorted(existing.items()):
                    f.write(f"{key}={value}\n")
        
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
            
            for name, value in secrets.items():
                if not value:
                    continue
                try:
                    result = subprocess.run(
                        ["gh", "secret", "set", name, "--body", value],
                        cwd=str(project_root),
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    results.append({
                        "name": name,
                        "success": result.returncode == 0,
                        "error": result.stderr if result.returncode != 0 else None,
                    })
                except Exception as e:
                    results.append({
                        "name": name,
                        "success": False,
                        "error": str(e),
                    })
        
        return jsonify({
            "env_saved": save_to_env,
            "results": results,
            "all_success": all(r["success"] for r in results) if results else True,
        })
    
    @app.route("/api/gh/status")
    def api_gh_status():
        """Get gh CLI status."""
        from ..config.system_status import check_tool
        status = check_tool("gh")
        return jsonify(status.to_dict())
    
    @app.route("/api/gh/auto")
    def api_gh_auto():
        """Get GitHub token from gh CLI and detect repo from git remote."""
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
    
    @app.route("/api/gh/secrets")
    def api_gh_secrets():
        """Get list of secrets set in GitHub repo."""
        try:
            # Check if gh is installed and authenticated
            from ..config.system_status import check_tool
            gh_status = check_tool("gh")
            
            if not gh_status.installed:
                return jsonify({
                    "available": False,
                    "reason": "gh CLI not installed",
                    "secrets": [],
                })
            
            if not gh_status.authenticated:
                return jsonify({
                    "available": False,
                    "reason": "gh CLI not authenticated",
                    "secrets": [],
                })
            
            # Get list of secrets from GitHub
            result = subprocess.run(
                ["gh", "secret", "list"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=15,
            )
            
            if result.returncode != 0:
                return jsonify({
                    "available": False,
                    "reason": result.stderr or "Failed to list secrets",
                    "secrets": [],
                })
            
            # Parse secret names from output (format: "NAME\tUpdated YYYY-MM-DD")
            secret_names = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    if parts:
                        secret_names.append(parts[0])
            
            return jsonify({
                "available": True,
                "secrets": secret_names,
            })
        
        except Exception as e:
            return jsonify({
                "available": False,
                "reason": str(e),
                "secrets": [],
            })
    
    @app.route("/api/secret/set", methods=["POST"])
    def api_secret_set():
        """Set a single secret to .env and/or GitHub."""
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
                    with open(env_file, "r") as f:
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
            try:
                result = subprocess.run(
                    ["gh", "secret", "set", name],
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
    
    @app.route("/api/secret/remove", methods=["POST"])
    def api_secret_remove():
        """Remove a secret from .env and/or GitHub."""
        data = request.json or {}
        name = data.get("name")
        target = data.get("target", "both")  # "local", "github", or "both"
        
        if not name:
            return jsonify({"error": "Secret name required"}), 400
        
        results = {"name": name, "local": None, "github": None}
        
        # Remove from .env
        if target in ("local", "both"):
            try:
                env_file = project_root / ".env"
                if env_file.exists():
                    lines = []
                    with open(env_file, "r") as f:
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
            try:
                result = subprocess.run(
                    ["gh", "secret", "remove", name],
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
    
    @app.route("/api/gh/install", methods=["POST"])
    def api_gh_install():
        """Spawn terminal to install gh CLI (user can enter sudo password)."""
        import platform
        
        system = platform.system().lower()
        
        if system == "linux":
            # Full install command
            install_script = '''#!/bin/bash
echo "Installing GitHub CLI..."
(type -p wget >/dev/null || (sudo apt update && sudo apt install wget -y)) \
    && sudo mkdir -p -m 755 /etc/apt/keyrings \
    && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    && cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
    && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && sudo mkdir -p -m 755 /etc/apt/sources.list.d \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && sudo apt update \
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
    
    @app.route("/api/state/reset", methods=["POST"])
    def api_state_reset():
        """Reset state to OK (calls CLI: reset)."""
        try:
            result = subprocess.run(
                ["python", "-m", "src.main", "reset", "-y"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return jsonify({
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else None,
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    
    @app.route("/api/state/factory-reset", methods=["POST"])
    def api_factory_reset():
        """Full factory reset (calls CLI: reset --full)."""
        data = request.json or {}
        backup = data.get("backup", True)
        hours = data.get("hours", 48)
        
        cmd = ["python", "-m", "src.main", "reset", "--full", "-y", "--hours", str(hours)]
        if backup:
            cmd.append("--backup")
        else:
            cmd.append("--no-backup")
        
        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return jsonify({
                        "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else None,
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    
    @app.route("/api/git/sync", methods=["POST"])
    def api_git_sync():
        """Commit all changes and push to remote."""
        data = request.json or {}
        message = data.get("message", "chore: sync from admin panel")

        steps = []
        try:
            # Stage all changes
            result = subprocess.run(
                ["git", "add", "-A"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=15,
            )
            steps.append({"step": "git add", "ok": result.returncode == 0})

            # Check if there's anything to commit
            result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Nothing staged
                return jsonify({
                    "success": True,
                    "message": "Already up to date (nothing to commit)",
                    "steps": steps,
                })

            # Commit
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=15,
            )
            steps.append({
                "step": "git commit",
                "ok": result.returncode == 0,
                "output": result.stdout.strip(),
            })
            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": result.stderr.strip() or "Commit failed",
                    "steps": steps,
                })

            # Push
            result = subprocess.run(
                ["git", "push"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            steps.append({
                "step": "git push",
                "ok": result.returncode == 0,
                "output": (result.stdout or result.stderr or "").strip(),
            })
            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": result.stderr.strip() or "Push failed",
                    "steps": steps,
                })

            return jsonify({
                "success": True,
                "message": "Committed and pushed successfully",
                "steps": steps,
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e), "steps": steps}), 500

    return app


def kill_port(port: int) -> bool:
    """
    Kill any process running on the specified port.
    
    Returns True if a process was killed, False otherwise.
    """
    import signal
    
    try:
        # Use lsof to find PID on port
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
        )
        
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                try:
                    pid_int = int(pid.strip())
                    os.kill(pid_int, signal.SIGTERM)
                    logger.info(f"Killed process {pid_int} on port {port}")
                except (ValueError, ProcessLookupError):
                    pass
            return True
    except FileNotFoundError:
        # lsof not available, try ss
        try:
            result = subprocess.run(
                ["ss", "-tlnp", f"sport = :{port}"],
                capture_output=True,
                text=True,
            )
            # Parse PID from ss output
            for line in result.stdout.split("\n"):
                if f":{port}" in line and "pid=" in line:
                    # Extract pid from something like "users:(("python3",pid=12345,fd=5))"
                    import re
                    match = re.search(r"pid=(\d+)", line)
                    if match:
                        try:
                            pid = int(match.group(1))
                            os.kill(pid, signal.SIGTERM)
                            logger.info(f"Killed process {pid} on port {port}")
                            return True
                        except (ValueError, ProcessLookupError):
                            pass
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Could not check/kill port {port}: {e}")
    
    return False


def run_server(
    host: str = "127.0.0.1",
    port: int = 5050,
    open_browser: bool = True,
    debug: bool = False,
) -> None:
    """
    Run the admin server.
    
    Args:
        host: Bind address (default: localhost only)
        port: Port to run on
        open_browser: Whether to open browser automatically
        debug: Enable Flask debug mode
    """
    # Kill any existing process on the port
    if kill_port(port):
        print(f"Killed existing process on port {port}")
        import time
        time.sleep(0.5)  # Give it time to release the port
    
    app = create_app()
    
    url = f"http://{host}:{port}"
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║              CONTINUITY ORCHESTRATOR ADMIN                   ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Local admin server running at:                              ║
║  → {url:<54} ║
║                                                              ║
║  Press Ctrl+C to stop                                        ║
║                                                              ║
║  ⚠️  This server is for LOCAL USE ONLY                       ║
║     Never expose to the internet!                            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    # Open browser after a short delay
    if open_browser:
        def open_browser_delayed():
            webbrowser.open(url)
        Timer(1.5, open_browser_delayed).start()
    
    # Run the server
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_server()
