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
    
    @app.route("/api/gh/install", methods=["POST"])
    def api_gh_install():
        """Install gh CLI using system package manager."""
        import platform
        
        # Detect OS and use appropriate install command
        system = platform.system().lower()
        
        if system == "linux":
            # Try apt first (Debian/Ubuntu)
            commands = [
                ["sudo", "apt", "update"],
                ["sudo", "apt", "install", "-y", "gh"],
            ]
        elif system == "darwin":
            # macOS with Homebrew
            commands = [
                ["brew", "install", "gh"],
            ]
        else:
            return jsonify({
                "error": f"Unsupported OS: {system}",
                "install_hint": "Visit https://cli.github.com/ for installation instructions",
            }), 400
        
        output_lines = []
        for cmd in commands:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                output_lines.append(f"$ {' '.join(cmd)}")
                if result.stdout:
                    output_lines.append(result.stdout)
                if result.returncode != 0:
                    return jsonify({
                        "success": False,
                        "error": result.stderr,
                        "output": "\n".join(output_lines),
                    }), 500
            except subprocess.TimeoutExpired:
                return jsonify({
                    "success": False,
                    "error": "Installation timed out",
                }), 504
            except Exception as e:
                return jsonify({
                    "success": False,
                    "error": str(e),
                }), 500
        
        # Verify installation
        from ..config.system_status import check_tool
        gh_status = check_tool("gh")
        
        return jsonify({
            "success": gh_status.installed,
            "version": gh_status.version,
            "output": "\n".join(output_lines),
            "needs_auth": not gh_status.authenticated if gh_status.installed else False,
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
    
    return app


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
