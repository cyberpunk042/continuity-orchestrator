"""
Admin API — Core dashboard and state management endpoints.

Blueprint: core_bp
Prefix: /api
Routes:
    /             (index — serves dashboard HTML)
    /api/status
    /api/run
    /api/test/email
    /api/test/sms
    /api/renew
    /api/state/set-deadline
    /api/state/reset
    /api/state/factory-reset
"""

from __future__ import annotations

import subprocess

from flask import Blueprint, current_app, jsonify, request, render_template
from pathlib import Path

from .helpers import fresh_env

core_bp = Blueprint("core", __name__)


def _project_root():
    return current_app.config["PROJECT_ROOT"]



def _env():
    return fresh_env(_project_root())


@core_bp.route("/")
def index():
    """Serve the admin dashboard."""
    return render_template("index.html")


@core_bp.route("/api/status")
def api_status():
    """Get comprehensive system status."""
    from ..config.system_status import get_system_status

    project_root = _project_root()
    status = get_system_status(
        state_file=project_root / "state" / "current.json",
        policy_dir=project_root / "policy",
    )
    return jsonify(status.to_dict())


@core_bp.route("/api/run", methods=["POST"])
def api_run():
    """Run a command."""
    project_root = _project_root()
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
        "circuit-breakers --reset": ["python", "-m", "src.main", "circuit-breakers", "--reset"],
        "test email": ["python", "-m", "src.main", "test", "email"],
        "test sms": ["python", "-m", "src.main", "test", "sms"],
        # Immediate FULL disclosure (no delay)
        "trigger-release-full": ["python", "-m", "src.main", "trigger-release", "--stage", "FULL", "--delay", "0"],
        # Shadow mode: stealth trigger with delay (same as entering RELEASE_SECRET via public site)
        "trigger-shadow-0": ["python", "-m", "src.main", "trigger-release", "--stage", "FULL", "--delay", "0", "--silent"],
        "trigger-shadow-30": ["python", "-m", "src.main", "trigger-release", "--stage", "FULL", "--delay", "30", "--silent"],
        "trigger-shadow-60": ["python", "-m", "src.main", "trigger-release", "--stage", "FULL", "--delay", "60", "--silent"],
        "trigger-shadow-120": ["python", "-m", "src.main", "trigger-release", "--stage", "FULL", "--delay", "120", "--silent"],
        "reset": ["python", "-m", "src.main", "reset", "-y"],
        # Trigger GitHub deploy-site workflow
        "deploy-site": ["gh", "workflow", "run", "deploy-site.yml"],
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
            env=_env(),  # Disable ANSI codes
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


@core_bp.route("/api/test/email", methods=["POST"])
def api_test_email():
    """Send a test email with optional custom recipient/subject/body."""
    project_root = _project_root()
    data = request.json or {}
    cmd = ["python", "-m", "src.main", "test", "email"]
    if data.get("to"):
        cmd += ["--to", data["to"]]
    if data.get("subject"):
        cmd += ["--subject", data["subject"]]
    if data.get("body"):
        cmd += ["--body", data["body"]]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
            env=_env(),
        )
        return jsonify({
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Command timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/test/sms", methods=["POST"])
def api_test_sms():
    """Send a test SMS with optional custom recipient/message."""
    project_root = _project_root()
    data = request.json or {}
    cmd = ["python", "-m", "src.main", "test", "sms"]
    if data.get("to"):
        cmd += ["--to", data["to"]]
    if data.get("message"):
        cmd += ["--message", data["message"]]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
            env=_env(),
        )
        return jsonify({
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Command timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/renew", methods=["POST"])
def api_renew():
    """Renew the deadline."""
    project_root = _project_root()
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


@core_bp.route("/api/state/set-deadline", methods=["POST"])
def api_set_deadline():
    """Set the countdown deadline via CLI."""
    project_root = _project_root()
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


@core_bp.route("/api/state/reset", methods=["POST"])
def api_state_reset():
    """Reset state to OK (calls CLI: reset)."""
    project_root = _project_root()
    try:
        result = subprocess.run(
            ["python", "-m", "src.main", "reset", "-y"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
            env=_env(),
        )
        return jsonify({
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@core_bp.route("/api/state/factory-reset", methods=["POST"])
def api_factory_reset():
    """Full factory reset (calls CLI: reset --full)."""
    project_root = _project_root()
    data = request.json or {}
    backup = data.get("backup", True)
    hours = data.get("hours", 48)
    include_content = data.get("include_content", False)
    purge_history = data.get("purge_history", False)
    decrypt_content = data.get("decrypt_content", False)
    scaffold = data.get("scaffold", True)

    cmd = ["python", "-m", "src.main", "reset", "--full", "-y", "--hours", str(hours)]
    if backup:
        cmd.append("--backup")
    else:
        cmd.append("--no-backup")
    if include_content:
        cmd.append("--include-content")
    if purge_history:
        cmd.append("--purge-history")
    if decrypt_content:
        cmd.append("--decrypt-content")
    if not scaffold:
        cmd.append("--no-scaffold")

    # History purge via git filter-repo may take longer
    timeout = 120 if purge_history else 30

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return jsonify({
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@core_bp.route("/api/state/trigger", methods=["POST"])
def api_state_trigger():
    """Trigger disclosure escalation to a specific stage.

    Accepts:
        stage: PRE_RELEASE | PARTIAL | FULL (default: FULL)
        delay: minutes before execution (default: 0)
        silent: if true, use shadow mode (default: false)
    """
    project_root = _project_root()
    data = request.json or {}
    stage = data.get("stage", "FULL")
    delay = int(data.get("delay", 0))
    silent = data.get("silent", False)

    valid_stages = {"REMIND_1", "REMIND_2", "PRE_RELEASE", "PARTIAL", "FULL"}
    if stage not in valid_stages:
        return jsonify({"success": False, "error": f"Invalid stage: {stage}. Must be one of {valid_stages}"}), 400

    cmd = [
        "python", "-m", "src.main", "trigger-release",
        "--stage", stage,
        "--delay", str(delay),
    ]
    if silent:
        cmd.append("--silent")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=60,
            env=_env(),
        )
        return jsonify({
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Command timed out"}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@core_bp.route("/api/content/scaffold", methods=["POST"])
def api_scaffold():
    """Regenerate default articles (How It Works, Full Disclosure Statement)."""
    from ..content.scaffold import generate_scaffold

    project_root = _project_root()
    data = request.json or {}
    overwrite = data.get("overwrite", False)

    result = generate_scaffold(project_root, overwrite=overwrite)
    return jsonify({
        "success": True,
        "created": result["created"],
        "skipped": result["skipped"],
    })

