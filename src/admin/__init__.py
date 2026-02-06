"""
Local Admin Server — Web-based management interface.

This module provides a local web server for managing the Continuity Orchestrator.
It's an alternative to manage.sh with a visual interface.

Usage:
    python -m src.admin
    # Opens browser to http://localhost:5000

Features:
    - View system status (stage, deadline, countdown)
    - View configuration status (adapters, secrets, tools)
    - Run commands (tick, renew, build-site)
    - Push secrets to GitHub (if gh is installed)
"""

from .server import create_app, run_server

__all__ = ["create_app", "run_server"]
