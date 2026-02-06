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
    
    @app.route("/api/secrets/push", methods=["POST"])
    def api_push_secrets():
        """Push secrets to GitHub using gh CLI."""
        data = request.json or {}
        secrets = data.get("secrets", {})
        
        # Check if gh is installed and authenticated
        from ..config.system_status import check_tool
        gh_status = check_tool("gh")
        
        if not gh_status.installed:
            return jsonify({
                "error": "gh CLI not installed",
                "install_hint": gh_status.install_hint,
            }), 400
        
        if not gh_status.authenticated:
            return jsonify({
                "error": "gh CLI not authenticated. Run: gh auth login",
            }), 400
        
        results = []
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
            "results": results,
            "all_success": all(r["success"] for r in results),
        })
    
    @app.route("/api/gh/status")
    def api_gh_status():
        """Get gh CLI status."""
        from ..config.system_status import check_tool
        status = check_tool("gh")
        return jsonify(status.to_dict())
    
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
