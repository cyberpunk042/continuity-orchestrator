"""
Admin API — Mirror management endpoints.

Blueprint: mirror_bp
Prefix: /api/mirror
"""

from __future__ import annotations

import json
import subprocess

from flask import Blueprint, current_app, jsonify, request

from .helpers import fresh_env

mirror_bp = Blueprint("mirror", __name__)


def _project_root():
    return current_app.config["PROJECT_ROOT"]


def _env():
    return fresh_env(_project_root())


@mirror_bp.route("/status", methods=["GET"])
def api_mirror_status():
    """Get mirror status via CLI."""
    try:
        result = subprocess.run(
            ["python", "-m", "src.main", "mirror-status", "--json"],
            cwd=str(_project_root()),
            capture_output=True,
            text=True,
            timeout=15,
            env=_env(),
        )
        lock = _project_root() / "state" / ".mirror_sync_lock"
        if result.returncode == 0:
            data = json.loads(result.stdout)
            data["syncing"] = lock.exists()
            return jsonify(data)
        return jsonify({"enabled": False, "syncing": lock.exists(), "error": result.stderr.strip()})
    except Exception as e:
        return jsonify({"enabled": False, "syncing": False, "error": str(e)})


@mirror_bp.route("/sync/stream")
def api_mirror_sync_stream():
    """SSE endpoint — streams mirror sync progress line by line."""
    mode = request.args.get("mode", "all")  # all, code, secrets, vars
    cmd = ["python", "-m", "src.main", "mirror-sync", "--json-lines"]
    if mode == "code":
        cmd.append("--code-only")
    elif mode == "secrets":
        cmd.append("--secrets-only")
    elif mode == "vars":
        cmd.append("--vars-only")

    root = _project_root()
    env = _env()

    def generate():
        proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            for line in proc.stdout:
                line = line.strip()
                if line:
                    yield f"data: {line}\n\n"
            proc.wait(timeout=120)
            # If there was stderr output (logging), send it as info
            stderr_out = proc.stderr.read()
            if stderr_out and proc.returncode != 0:
                yield f"data: {json.dumps({'step': 'error', 'status': 'failed', 'error': stderr_out.strip()})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'step': 'error', 'status': 'failed', 'error': str(e)})}\n\n"
        finally:
            proc.kill() if proc.poll() is None else None

    return current_app.response_class(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@mirror_bp.route("/clean/stream")
def api_mirror_clean_stream():
    """SSE endpoint — streams mirror clean progress."""
    mode = request.args.get("mode", "all")  # all, code, secrets, variables
    cmd = ["python", "-m", "src.main", "mirror-clean", "--json-lines", "--yes"]
    if mode == "code":
        cmd.append("--code")
    elif mode == "secrets":
        cmd.append("--secrets")
    elif mode == "variables":
        cmd.append("--variables")
    else:
        cmd.append("--all")

    root = _project_root()
    env = _env()

    def generate():
        proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            for line in proc.stdout:
                line = line.strip()
                if line:
                    yield f"data: {line}\n\n"
            proc.wait(timeout=120)
            stderr_out = proc.stderr.read()
            if stderr_out and proc.returncode != 0:
                yield f"data: {json.dumps({'step': 'error', 'status': 'failed', 'error': stderr_out.strip()})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'step': 'error', 'status': 'failed', 'error': str(e)})}\n\n"
        finally:
            proc.kill() if proc.poll() is None else None

    return current_app.response_class(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Legacy endpoints (kept for backward compat / simple calls)
@mirror_bp.route("/sync", methods=["POST"])
def api_mirror_sync():
    """Run full mirror sync (non-streaming fallback)."""
    try:
        result = subprocess.run(
            ["python", "-m", "src.main", "mirror-sync"],
            cwd=str(_project_root()), capture_output=True, text=True,
            timeout=120, env=_env(),
        )
        combined = (result.stdout or "") + (result.stderr or "")
        return jsonify({"success": result.returncode == 0, "output": combined.strip()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@mirror_bp.route("/sync/code", methods=["POST"])
def api_mirror_sync_code():
    """Run code-only sync (non-streaming fallback)."""
    try:
        result = subprocess.run(
            ["python", "-m", "src.main", "mirror-sync", "--code-only"],
            cwd=str(_project_root()), capture_output=True, text=True,
            timeout=120, env=_env(),
        )
        combined = (result.stdout or "") + (result.stderr or "")
        return jsonify({"success": result.returncode == 0, "output": combined.strip()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@mirror_bp.route("/sync/secrets", methods=["POST"])
def api_mirror_sync_secrets():
    """Run secrets-only sync (non-streaming fallback)."""
    try:
        result = subprocess.run(
            ["python", "-m", "src.main", "mirror-sync", "--secrets-only"],
            cwd=str(_project_root()), capture_output=True, text=True,
            timeout=120, env=_env(),
        )
        combined = (result.stdout or "") + (result.stderr or "")
        return jsonify({"success": result.returncode == 0, "output": combined.strip()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
