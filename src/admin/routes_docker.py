"""
Admin API — Docker container management endpoints.

Blueprint: docker_bp
Prefix: /api/docker
Routes:
    /api/docker/status     GET   Container status for all Continuity services
    /api/docker/restart    POST  Restart services (profile-aware)
    /api/docker/start      POST  Start/rebuild services (always passes --build)
    /api/docker/stop       POST  Stop services (with optional volume/image cleanup)
    /api/docker/build      POST  Build images (with optional --no-cache)
    /api/docker/logs       GET   Fetch recent container logs
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from flask import Blueprint, current_app, jsonify, request

from .helpers import fresh_env

docker_bp = Blueprint("docker", __name__)
logger = logging.getLogger(__name__)


# ── Container ↔ Profile mapping ──────────────────────────────────────
# From docker-compose.yml:
#   orchestrator          → (no profile) — standalone test mode
#   orchestrator-git-sync → git-sync     — production with git sync
#   nginx                 → (no profile) — always runs
#   cloudflared           → tunnel       — optional Cloudflare tunnel
#   site-builder          → tools        — one-shot
#   health-check          → tools        — one-shot

CONTAINER_PROFILE_MAP = {
    "continuity-git-sync": "git-sync",
    "continuity-tunnel": "tunnel",
    # No profile needed for these (they always start):
    "continuity-orchestrator": None,
    "continuity-nginx": None,
}

# Containers we care about for status display (skip init + one-shots)
DISPLAY_CONTAINERS = [
    "continuity-orchestrator",
    "continuity-git-sync",
    "continuity-nginx",
    "continuity-tunnel",
]


def _project_root() -> Path:
    return current_app.config["PROJECT_ROOT"]


def _docker_available() -> bool:
    """Check if docker CLI is available."""
    return shutil.which("docker") is not None


def _compose_file_exists() -> bool:
    """Check if docker-compose.yml exists in project root."""
    return (_project_root() / "docker-compose.yml").exists()


def _run_compose(*args: str, profiles: Optional[List[str]] = None,
                 timeout: int = 30) -> dict:
    """
    Run a docker compose command with correct profiles.

    Args:
        *args: Command arguments (e.g. 'ps', '--format', 'json')
        profiles: Explicit profile list. If None, auto-detect.
        timeout: Command timeout in seconds.

    Returns:
        dict with success, output, error keys.
    """
    cmd = ["docker", "compose"]

    # Add profile flags
    if profiles is not None:
        for p in profiles:
            cmd.extend(["--profile", p])
    else:
        # Auto-detect from running containers
        detected = _detect_active_profiles()
        cmd.extend(detected)

    cmd.extend(args)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(_project_root()),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Command timed out"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


def _detect_active_profiles() -> list:
    """
    Detect which profiles are active by checking running containers.

    Returns list of profile flags: ['--profile', 'git-sync', '--profile', 'tunnel']
    """
    flags = []

    # Query all containers with all profiles to see what's running
    try:
        result = subprocess.run(
            ["docker", "compose",
             "--profile", "git-sync",
             "--profile", "tunnel",
             "ps", "--format", "json"],
            cwd=str(_project_root()),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return flags

        containers = _parse_compose_ps(result.stdout)
        running_names = {
            c["Name"] for c in containers
            if c.get("State", "").lower() == "running"
        }

        if "continuity-git-sync" in running_names:
            flags.extend(["--profile", "git-sync"])
        if "continuity-tunnel" in running_names:
            flags.extend(["--profile", "tunnel"])

    except Exception as e:
        logger.warning("Failed to detect active profiles: %s", e)

    return flags


def _parse_compose_ps(stdout: str) -> list:
    """
    Parse `docker compose ps --format json` output.

    Docker Compose v2 outputs one JSON object per line (NDJSON),
    not a JSON array.
    """
    containers = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            containers.append(obj)
        except json.JSONDecodeError:
            continue
    return containers


def _get_container_status() -> list:
    """
    Get status for all known Continuity containers.
    Returns a list of container status dicts for display.
    """
    # Query with ALL profiles to see everything
    result = subprocess.run(
        ["docker", "compose",
         "--profile", "git-sync",
         "--profile", "tunnel",
         "ps", "--format", "json", "-a"],
        cwd=str(_project_root()),
        capture_output=True,
        text=True,
        timeout=10,
    )

    found = {}
    if result.returncode == 0:
        containers = _parse_compose_ps(result.stdout)
        for c in containers:
            name = c.get("Name", "")
            if name in DISPLAY_CONTAINERS:
                state = c.get("State", "unknown").lower()
                found[name] = {
                    "name": name,
                    "service": c.get("Service", ""),
                    "status": state,
                    "state": c.get("Status", ""),  # "Up 2 hours", etc.
                    "profile": CONTAINER_PROFILE_MAP.get(name),
                }

    # Fill in containers that aren't running at all
    for name in DISPLAY_CONTAINERS:
        if name not in found:
            found[name] = {
                "name": name,
                "service": "",
                "status": "not_found",
                "state": None,
                "profile": CONTAINER_PROFILE_MAP.get(name),
            }

    return list(found.values())


# ── Routes ────────────────────────────────────────────────────────────


@docker_bp.route("/status", methods=["GET"])
def docker_status():
    """Get container status for all known Continuity services."""
    if not _docker_available():
        return jsonify({
            "available": False,
            "compose_file": False,
            "error": "Docker CLI not found",
        })

    if not _compose_file_exists():
        return jsonify({
            "available": True,
            "compose_file": False,
            "error": "docker-compose.yml not found in project root",
        })

    try:
        containers = _get_container_status()

        # Detect active profiles from running containers
        running_names = {c["name"] for c in containers if c["status"] == "running"}
        active_profiles = []
        if "continuity-git-sync" in running_names:
            active_profiles.append("git-sync")
        if "continuity-tunnel" in running_names:
            active_profiles.append("tunnel")

        # Read git-sync config from env
        env = fresh_env(_project_root())
        git_sync_config = {
            "alpha": env.get("DOCKER_GIT_SYNC_ALPHA", "false").lower() == "true",
            "tick_interval": int(env.get("DOCKER_GIT_SYNC_TICK_INTERVAL", "900")),
            "sync_interval": int(env.get("DOCKER_GIT_SYNC_SYNC_INTERVAL", "30")),
        }

        return jsonify({
            "available": True,
            "compose_file": True,
            "active_profiles": active_profiles,
            "containers": containers,
            "git_sync_config": git_sync_config,
        })

    except Exception as e:
        logger.error("Failed to get Docker status: %s", e)
        return jsonify({
            "available": True,
            "compose_file": True,
            "error": str(e),
        }), 500


@docker_bp.route("/restart", methods=["POST"])
def docker_restart():
    """Restart services: down + up --build (re-reads compose, rebuilds if needed)."""
    if not _docker_available():
        return jsonify({"success": False, "error": "Docker CLI not found"}), 400

    # Detect active profiles BEFORE tearing down
    profile_flags = _detect_active_profiles()
    # Convert flags ['--profile', 'git-sync', ...] to list ['git-sync', ...]
    active = [profile_flags[i + 1]
              for i in range(0, len(profile_flags), 2)]

    # Step 1: down
    down = _run_compose("down", profiles=active, timeout=60)
    if not down["success"]:
        return jsonify({
            "success": False,
            "output": down["output"],
            "error": f"down failed: {down['error']}",
        })

    # Step 2: up --build with the same profiles
    up = _run_compose("up", "-d", "--build",
                      profiles=active, timeout=300)

    return jsonify({
        "success": up["success"],
        "output": up["output"],
        "error": up["error"],
    })


@docker_bp.route("/start", methods=["POST"])
def docker_start():
    """Start services with specified profiles.

    Always passes --build so Docker's layer cache handles image
    freshness automatically. If nothing changed, the build is near-instant.
    If source files changed, only invalidated layers are rebuilt.

    Body: { "profiles": ["git-sync"] }
      or: { "profiles": ["git-sync", "tunnel"] }
      or: {} for standalone mode
    """
    if not _docker_available():
        return jsonify({"success": False, "error": "Docker CLI not found"}), 400

    data = request.get_json(silent=True) or {}
    profiles = data.get("profiles", [])

    # Validate profiles
    allowed_profiles = {"git-sync", "tunnel"}
    for p in profiles:
        if p not in allowed_profiles:
            return jsonify({
                "success": False,
                "error": f"Unknown profile: {p}",
            }), 400

    # --build: Docker's layer cache ensures this is fast when nothing changed
    result = _run_compose("up", "-d", "--build", profiles=profiles, timeout=300)

    return jsonify({
        "success": result["success"],
        "output": result["output"],
        "error": result["error"],
    })


@docker_bp.route("/build", methods=["POST"])
def docker_build():
    """Build (or rebuild) images.

    Uses Docker's layer cache by default, so unchanged layers are
    reused automatically. Pass no_cache to force a full rebuild.

    Body: { "profiles": ["git-sync"], "no_cache": false }
    """
    if not _docker_available():
        return jsonify({"success": False, "error": "Docker CLI not found"}), 400

    data = request.get_json(silent=True) or {}
    profiles = data.get("profiles", [])
    no_cache = data.get("no_cache", False)

    # Validate profiles
    allowed_profiles = {"git-sync", "tunnel"}
    for p in profiles:
        if p not in allowed_profiles:
            return jsonify({
                "success": False,
                "error": f"Unknown profile: {p}",
            }), 400

    args = ["build"]
    if no_cache:
        args.append("--no-cache")

    result = _run_compose(*args, profiles=profiles, timeout=600)

    return jsonify({
        "success": result["success"],
        "output": result["output"],
        "error": result["error"],
    })


@docker_bp.route("/stop", methods=["POST"])
def docker_stop():
    """Stop services using auto-detected profiles.

    Body (all optional):
        remove_volumes: bool  — also remove named volumes (data loss!)
        remove_images:  bool  — also remove locally-built images
    """
    if not _docker_available():
        return jsonify({"success": False, "error": "Docker CLI not found"}), 400

    data = request.get_json(silent=True) or {}
    remove_volumes = data.get("remove_volumes", False)
    remove_images = data.get("remove_images", False)

    args = ["down"]
    if remove_volumes:
        args.append("-v")
    if remove_images:
        args.extend(["--rmi", "local"])

    result = _run_compose(*args, timeout=120)

    return jsonify({
        "success": result["success"],
        "output": result["output"],
        "error": result["error"],
        "cleaned": {
            "volumes": remove_volumes,
            "images": remove_images,
        },
    })


@docker_bp.route("/logs", methods=["GET"])
def docker_logs():
    """Fetch recent container logs.

    Query params:
        service: service name (e.g. 'orchestrator-git-sync')
        lines: number of lines (default 100, max 500)
    """
    if not _docker_available():
        return jsonify({"success": False, "error": "Docker CLI not found"}), 400

    service = request.args.get("service", "")
    lines = min(int(request.args.get("lines", "100")), 500)

    args = ["logs", "--tail", str(lines), "--no-color"]
    if service:
        args.append(service)

    result = _run_compose(*args, timeout=15)

    return jsonify({
        "success": result["success"],
        "output": result["output"],
        "error": result["error"],
        "service": service or "all",
        "lines": lines,
    })
