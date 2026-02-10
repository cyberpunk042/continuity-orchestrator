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
    /api/audit
"""

from __future__ import annotations

import json
import subprocess

from flask import Blueprint, current_app, jsonify, render_template, request

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
        # Trigger GitHub cron (tick) workflow
        "trigger-cron": ["gh", "workflow", "run", "cron.yml"],
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


@core_bp.route("/api/test/x", methods=["POST"])
def api_test_x():
    """Verify X (Twitter) API credentials, optionally post a test tweet."""
    project_root = _project_root()
    data = request.json or {}
    cmd = ["python", "-m", "src.main", "test", "x"]
    if data.get("post"):
        cmd.append("--post")
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

        output = result.stdout
        error = result.stderr if result.returncode != 0 else None

        # If reset succeeded and policy reset requested, apply default preset
        reset_policy = data.get("reset_policy", False)
        if result.returncode == 0 and reset_policy:
            policy_result = subprocess.run(
                ["python", "-m", "src.main", "policy-constants",
                 "--preset", "default", "--json-output"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=15,
                env=_env(),
            )
            if policy_result.returncode == 0:
                output += "\n✅ Policy reset to defaults"
                # Bundle the policy change into a git commit so it's not left dirty
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=str(project_root),
                    capture_output=True, text=True, timeout=10,
                )
                commit_result = subprocess.run(
                    ["git", "commit", "-m",
                     "chore: factory reset — policy restored to defaults"],
                    cwd=str(project_root),
                    capture_output=True, text=True, timeout=15,
                )
                if commit_result.returncode == 0:
                    output += "\n📦 Policy change committed to git"
                    # Push the commit so user doesn't have to manually
                    push_result = subprocess.run(
                        ["git", "push"],
                        cwd=str(project_root),
                        capture_output=True, text=True, timeout=30,
                    )
                    if push_result.returncode == 0:
                        output += "\n🚀 Pushed to remote"
                    else:
                        output += f"\n⚠️ Push failed (run git push manually): {push_result.stderr}"
            else:
                output += f"\n⚠️ Policy reset failed: {policy_result.stderr}"

        return jsonify({
            "success": result.returncode == 0,
            "output": output,
            "error": error,
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


@core_bp.route("/api/policy/constants")
def api_policy_constants():
    """Read current policy constants and rule status."""
    project_root = _project_root()
    try:
        result = subprocess.run(
            ["python", "-m", "src.main", "policy-constants", "--json-output"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=15,
            env=_env(),
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            return jsonify(data)
        return jsonify({"error": result.stderr or "Command failed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@core_bp.route("/api/policy/constants", methods=["POST"])
def api_policy_constants_update():
    """Update policy constants, toggle rules, or apply presets."""
    project_root = _project_root()
    data = request.json or {}

    cmd = ["python", "-m", "src.main", "policy-constants", "--json-output"]

    # Apply preset
    preset = data.get("preset")
    if preset:
        cmd += ["--preset", preset]

    # Set constants
    constants = data.get("constants", {})
    for key, value in constants.items():
        cmd += ["--set", f"{key}={value}"]

    # Enable/disable rules
    for rule_id in data.get("enable", []):
        cmd += ["--enable", rule_id]
    for rule_id in data.get("disable", []):
        cmd += ["--disable", rule_id]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=15,
            env=_env(),
        )
        if result.returncode == 0:
            import json
            updated = json.loads(result.stdout)
            updated["success"] = True
            return jsonify(updated)
        return jsonify({
            "success": False,
            "error": result.stderr or "Command failed",
        }), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Audit Log ────────────────────────────────────────────────────

# Event type metadata for normalization and display
_AUDIT_TYPE_META = {
    "tick_start":       {"group": "ticks"},
    "tick_end":         {"group": "ticks"},
    "rule_matched":     {"group": "ticks"},
    "state_transition": {"group": "transitions"},
    "renewal":          {"group": "renewals"},
    "manual_release":   {"group": "releases"},
    "factory_reset":    {"group": "resets"},
}

# Fields that belong to the envelope, not to details
_AUDIT_ENVELOPE_KEYS = frozenset({
    "ts_iso", "timestamp", "event_id", "tick_id", "type", "event_type",
    "level", "escalation_state", "state_id", "policy_version", "plan_id",
    "details",
})


def _normalise_audit_entry(raw: dict) -> dict:
    """Normalise both old-format and new-format audit entries.

    Old format (from CLI):  {event_type, timestamp, ...}
    New format (AuditWriter): {type, ts_iso, event_id, ...}

    Returns a unified shape that the frontend can rely on.
    """
    entry = {
        "timestamp": raw.get("ts_iso") or raw.get("timestamp", ""),
        "event_id":  raw.get("event_id", ""),
        "tick_id":   raw.get("tick_id", ""),
        "type":      raw.get("type") or raw.get("event_type", "unknown"),
        "level":     raw.get("level", "info"),
        "state":     (raw.get("escalation_state")
                      or raw.get("new_state")
                      or raw.get("previous_state")
                      or ""),
        "details":   dict(raw.get("details") or {}),
    }

    # Merge remaining top-level keys into details so nothing is lost
    for key, value in raw.items():
        if key not in _AUDIT_ENVELOPE_KEYS and key not in entry["details"]:
            entry["details"][key] = value

    return entry


def _build_audit_summary(entries: list) -> dict:
    """Compute summary statistics from normalised entries."""
    summary: dict = {
        "total_events": len(entries),
        "total_ticks": 0,
        "total_renewals": 0,
        "total_transitions": 0,
        "total_releases": 0,
        "total_resets": 0,
    }

    for entry in entries:
        meta = _AUDIT_TYPE_META.get(entry["type"])
        if not meta:
            continue
        group = meta["group"]
        if group == "ticks" and entry["type"] == "tick_end":
            summary["total_ticks"] += 1
        elif group == "renewals":
            summary["total_renewals"] += 1
        elif group == "transitions":
            summary["total_transitions"] += 1
        elif group == "releases":
            summary["total_releases"] += 1
        elif group == "resets":
            summary["total_resets"] += 1

    # Find latest timestamps (entries are already newest-first)
    for entry in entries:
        if entry["type"] == "tick_end" and "last_tick_at" not in summary:
            summary["last_tick_at"] = entry["timestamp"]
        if entry["type"] == "renewal" and "last_renewal_at" not in summary:
            summary["last_renewal_at"] = entry["timestamp"]
        if summary.get("last_tick_at") and summary.get("last_renewal_at"):
            break  # Found both, stop scanning

    return summary


@core_bp.route("/api/audit")
def api_audit():
    """Read the audit ledger and return normalised entries + summary.

    Query params:
        limit (int): Max entries to return (default 500, max 2000).
    """
    project_root = _project_root()
    audit_path = project_root / "audit" / "ledger.ndjson"
    limit = min(request.args.get("limit", 500, type=int), 2000)

    if not audit_path.exists():
        return jsonify({"entries": [], "total": 0, "summary": {
            "total_events": 0, "total_ticks": 0, "total_renewals": 0,
            "total_transitions": 0, "total_releases": 0, "total_resets": 0,
        }})

    # Parse all lines
    entries = []
    for line in audit_path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        entries.append(_normalise_audit_entry(raw))

    # Newest first
    entries.reverse()

    summary = _build_audit_summary(entries)

    return jsonify({
        "entries": entries[:limit],
        "total": len(entries),
        "summary": summary,
    })


# ── Simulation ───────────────────────────────────────────────────

@core_bp.route("/api/simulate", methods=["POST"])
def api_simulate():
    """Run escalation simulation and return the predicted timeline.

    Body (JSON):
        hours (int): Duration to simulate (default 72, max 720).

    Returns JSON with ``simulation`` metadata and ``events`` list.
    """

    from ..cli.deploy import _run_simulation
    from ..persistence.state_file import load_state

    project_root = _project_root()
    data = request.json or {}
    hours = min(max(int(data.get("hours", 72)), 1), 720)

    state_path = project_root / "state" / "current.json"
    if not state_path.exists():
        return jsonify({"error": "No state file found"}), 404

    state = load_state(state_path)
    policy_path = project_root / "policy"

    try:
        result = _run_simulation(state, policy_path, hours=hours)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Sentinel Status ──────────────────────────────────────────────
@core_bp.route("/api/sentinel/status")
def api_sentinel_status():
    """Proxy the sentinel Worker /status endpoint for the dashboard."""
    import os

    url = os.environ.get("SENTINEL_URL", "").rstrip("/")
    if not url:
        return jsonify({"configured": False})

    try:
        import httpx

        resp = httpx.get(f"{url}/status", timeout=3)
        data = resp.json()
        data["configured"] = True
        data["reachable"] = True
        return jsonify(data)
    except Exception as e:
        return jsonify({
            "configured": True,
            "reachable": False,
            "error": str(e),
        })
