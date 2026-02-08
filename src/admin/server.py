"""
Local Admin Server — Flask-based web interface.

This provides a simple web server for local management.
It should NEVER be exposed to the internet.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import webbrowser
from pathlib import Path
from threading import Timer

from flask import Flask

from .routes_core import core_bp
from .routes_archive import archive_bp
from .routes_env import env_bp
from .routes_git import git_bp
from .routes_mirror import mirror_bp
from .routes_secrets import secrets_bp
from .routes_content import content_bp

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Create the Flask application."""

    # Get paths
    project_root = Path(__file__).parent.parent.parent
    static_folder = Path(__file__).parent / "static"
    template_folder = Path(__file__).parent / "templates"

    app = Flask(
        __name__,
        static_folder=str(static_folder),
        static_url_path="/static",
        template_folder=str(template_folder),
    )

    # Store project root for use in routes
    app.config["PROJECT_ROOT"] = project_root

    # Disable reloader warning
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # ── Register Blueprints ───────────────────────────────────────
    app.register_blueprint(core_bp)                                     # / + /api/*
    app.register_blueprint(archive_bp, url_prefix="/api/archive")       # /api/archive/*
    app.register_blueprint(env_bp, url_prefix="/api")                   # /api/env/*, /api/secrets/push
    app.register_blueprint(git_bp, url_prefix="/api/git")               # /api/git/*
    app.register_blueprint(mirror_bp, url_prefix="/api/mirror")         # /api/mirror/*
    app.register_blueprint(secrets_bp, url_prefix="/api")               # /api/gh/*, /api/secret/*
    app.register_blueprint(content_bp, url_prefix="/api/content")       # /api/content/*

    # ── Request Logging ───────────────────────────────────────────

    @app.before_request
    def log_request_start():
        """Record request start time."""
        import time
        from flask import request
        request._start_time = time.time()

    @app.after_request
    def log_request_end(response):
        """Log request with duration for API endpoints."""
        import time
        from flask import request
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

    return app


def kill_port(port: int) -> bool:
    """
    Kill any process running on the specified port.

    Returns True if a process was killed, False otherwise.
    """
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
