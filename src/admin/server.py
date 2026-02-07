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
    
    def _fresh_env() -> dict:
        """Build subprocess env with fresh .env values.
        
        The server process's os.environ is stale — it was loaded at startup.
        This reads the current .env file on each call so test commands
        (email, SMS, etc.) use the latest values.
        """
        env = {**os.environ, "TERM": "dumb"}
        env_file = project_root / ".env"
        if env_file.exists():
            with open(env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        # Strip surrounding quotes
                        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                            value = value[1:-1]
                        env[key] = value
        return env

    def _trigger_mirror_sync_bg(mode: str = "all") -> None:
        """Fire mirror-sync in the background if mirroring is enabled.
        
        Called after git sync or secrets push so the mirror stays up to date.
        Args:
            mode: 'all', 'code-only', or 'secrets-only'
        """
        env = _fresh_env()
        if env.get("MIRROR_ENABLED", "").lower() != "true":
            return
        cmd = ["python", "-m", "src.main", "mirror-sync"]
        if mode == "code-only":
            cmd.append("--code-only")
        elif mode == "secrets-only":
            cmd.append("--secrets-only")
        logger.info("[mirror-bg] Triggering background mirror-sync (%s)", mode)
        try:
            subprocess.Popen(
                cmd,
                cwd=str(project_root),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.warning("[mirror-bg] Failed to start mirror-sync: %s", e)

    def _gh_repo_flag() -> list:
        """Get -R repo flag for gh CLI commands.
        
        Required because mirror remotes cause gh to fail with
        'multiple remotes detected' when no -R is specified.
        """
        repo = _fresh_env().get("GITHUB_REPOSITORY", "")
        return ["-R", repo] if repo else []


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
                env=_fresh_env(),  # Disable ANSI codes
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

    @app.route("/api/test/email", methods=["POST"])
    def api_test_email():
        """Send a test email with optional custom recipient/subject/body."""
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
                env=_fresh_env(),
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

    @app.route("/api/test/sms", methods=["POST"])
    def api_test_sms():
        """Send a test SMS with optional custom recipient/message."""
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
                env=_fresh_env(),
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
        Archive URL(s) to the Internet Archive's Wayback Machine.
        
        Request body:
        - url: Optional URL to archive (defaults to GitHub Pages URL)
        - all_pages: If true, archive all key pages (index, articles, etc.)
        
        Returns:
        - success: bool
        - archive_url: The permanent Wayback Machine URL (single mode)
        - original_url: The URL that was archived (single mode)
        - results: Per-page results (all_pages mode)
        - error: Error message if failed
        """
        data = request.json or {}
        custom_url = data.get("url")
        all_pages = data.get("all_pages", False)
        
        logger.info(f"Archive request received. Custom URL: {custom_url}, all_pages: {all_pages}")
        
        try:
            from ..adapters.internet_archive import archive_url_now
            
            # Determine base URL
            if custom_url:
                base_url = custom_url.rstrip("/")
            else:
                # Try to get from environment
                archive_url = os.environ.get("ARCHIVE_URL")
                if archive_url:
                    base_url = archive_url.rstrip("/")
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
                    base_url = f"https://{parts[0]}.github.io/{parts[1]}"
            
            if all_pages:
                # Multi-page archiving
                from ..site.generator import SiteGenerator
                
                public_dir = project_root / "public"
                archivable_paths = SiteGenerator.get_archivable_paths(public_dir)
                
                logger.info(f"Archiving {len(archivable_paths)} pages from {base_url}")
                
                results = []
                for path in archivable_paths:
                    page_url = f"{base_url}/{path}" if path else f"{base_url}/"
                    label = path or "index"
                    
                    logger.info(f"Archiving: {label}")
                    page_result = archive_url_now(page_url)
                    results.append({
                        "page": label,
                        "url": page_url,
                        "success": page_result.get("success", False),
                        "archive_url": page_result.get("archive_url"),
                        "error": page_result.get("error"),
                    })
                    
                    # Rate limit between requests
                    if path != archivable_paths[-1]:
                        import time
                        time.sleep(5)
                
                success_count = sum(1 for r in results if r["success"])
                return jsonify({
                    "success": success_count > 0,
                    "results": results,
                    "total": len(results),
                    "archived": success_count,
                    "original_url": base_url,
                })
            else:
                # Single URL archiving (backwards compatible)
                url = f"{base_url}/"
                
                logger.info(f"Archiving URL: {url}")
                logger.debug("Archive may take up to 3 minutes")
                
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
        Check if URL(s) are already archived on the Wayback Machine.
        
        Request body:
        - url: URL to check (optional if all_pages)
        - all_pages: If true, check all key pages
        
        Returns:
        - archived: bool
        - snapshot: Latest snapshot info if archived (single mode)
        - results: Per-page status (all_pages mode)
        """
        data = request.json or {}
        url = data.get("url")
        all_pages = data.get("all_pages", False)
        
        try:
            from ..adapters.internet_archive import InternetArchiveAdapter
            
            if all_pages:
                # Determine base URL
                base_url = None
                if url:
                    base_url = url.rstrip("/")
                else:
                    archive_url = os.environ.get("ARCHIVE_URL")
                    if archive_url:
                        base_url = archive_url.rstrip("/")
                    else:
                        repo = os.environ.get("GITHUB_REPOSITORY")
                        if repo:
                            parts = repo.split("/")
                            base_url = f"https://{parts[0]}.github.io/{parts[1]}"
                
                if not base_url:
                    return jsonify({"error": "No URL to check. Set GITHUB_REPOSITORY or provide a URL."}), 400
                
                from ..site.generator import SiteGenerator
                archivable_paths = SiteGenerator.get_archivable_paths(project_root / "public")
                
                results = []
                for path in archivable_paths:
                    page_url = f"{base_url}/{path}" if path else f"{base_url}/"
                    label = path or "index"
                    snapshot = InternetArchiveAdapter.check_availability(page_url)
                    results.append({
                        "page": label,
                        "url": page_url,
                        "archived": snapshot is not None,
                        "snapshot": snapshot,
                    })
                
                archived_count = sum(1 for r in results if r["archived"])
                return jsonify({
                    "results": results,
                    "total": len(results),
                    "archived_count": archived_count,
                })
            else:
                # Single URL check
                if not url:
                    return jsonify({"error": "URL required"}), 400
                
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
        """Push secrets/variables to GitHub AND save to .env file.
        
        Request body:
            secrets: dict of name->value for GitHub secrets (gh secret set)
            variables: dict of name->value for GitHub variables (gh variable set)
            env_values: dict of name->value for .env saving (all values)
            deletions: list of names to delete from .env
            push_to_github: bool
            save_to_env: bool
            exclude_from_github: list of names to skip for GitHub push
        """
        data = request.json or {}
        secrets = data.get("secrets", {})
        variables = data.get("variables", {})
        env_values = data.get("env_values", {})
        deletions = data.get("deletions", [])
        push_to_github = data.get("push_to_github", True)
        save_to_env = data.get("save_to_env", True)
        exclude_from_github = set(data.get("exclude_from_github", []))
        
        # For .env saving: use env_values if provided, otherwise fall back to secrets+variables
        all_values = env_values if env_values else {**secrets, **variables}
        results = []
        deletions_applied = []
        
        # First, save to .env file
        if save_to_env and (all_values or deletions):
            env_file = project_root / ".env"
            existing = {}
            if env_file.exists():
                with open(env_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, value = line.partition("=")
                            existing[key.strip()] = value.strip()
            
            for name, value in all_values.items():
                if value:
                    existing[name] = f'"{value}"' if " " in value or "=" in value else value
            
            # Apply deletions
            for name in deletions:
                if name in existing:
                    del existing[name]
                    deletions_applied.append(name)
            
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
            
            # Push secrets via gh secret set
            repo_flag = _gh_repo_flag()
            for name, value in secrets.items():
                if not value:
                    continue
                if name.startswith("GITHUB_") or name in exclude_from_github:
                    continue
                try:
                    result = subprocess.run(
                        ["gh", "secret", "set", name, "--body", value] + repo_flag,
                        cwd=str(project_root),
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    results.append({
                        "name": name,
                        "kind": "secret",
                        "success": result.returncode == 0,
                        "error": result.stderr if result.returncode != 0 else None,
                    })
                except Exception as e:
                    results.append({
                        "name": name, "kind": "secret",
                        "success": False, "error": str(e),
                    })
            
            # Push variables via gh variable set
            for name, value in variables.items():
                if not value:
                    continue
                if name in exclude_from_github:
                    continue
                try:
                    result = subprocess.run(
                        ["gh", "variable", "set", name, "--body", value] + repo_flag,
                        cwd=str(project_root),
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    results.append({
                        "name": name,
                        "kind": "variable",
                        "success": result.returncode == 0,
                        "error": result.stderr if result.returncode != 0 else None,
                    })
                except Exception as e:
                    results.append({
                        "name": name, "kind": "variable",
                        "success": False, "error": str(e),
                    })
        all_ok = all(r["success"] for r in results) if results else True

        # Auto-sync secrets to mirror if enabled and push succeeded
        if push_to_github and all_ok and results:
            _trigger_mirror_sync_bg("secrets-only")

        return jsonify({
            "env_saved": save_to_env,
            "deletions_applied": deletions_applied,
            "results": results,
            "all_success": all_ok,
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
        """Get list of secrets AND variables set in GitHub repo."""
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
            
            repo_flag = _gh_repo_flag()

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
            repo_flag = _gh_repo_flag()
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
    
    @app.route("/api/secret/remove", methods=["POST"])
    def api_secret_remove():
        """Remove a secret/variable from .env and/or GitHub."""
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
            # Use correct gh command based on kind
            gh_cmd = "variable" if kind == "variable" else "secret"
            repo_flag = _gh_repo_flag()
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
                env=_fresh_env(),
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

    @app.route("/api/git/status", methods=["GET"])
    def api_git_status():
        """Return git repo status for the dashboard."""
        import shutil as _shutil

        if not _shutil.which("git"):
            return jsonify({"available": False, "error": "git not installed"})

        def _git(*args, timeout=10):
            result = subprocess.run(
                ["git"] + list(args),
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.stdout.strip() if result.returncode == 0 else None

        try:
            # Check if git repo
            if _git("rev-parse", "--is-inside-work-tree") is None:
                return jsonify({"available": False, "error": "Not a git repo"})

            branch = _git("branch", "--show-current") or "unknown"
            last_commit = _git("log", "-1", "--format=%h %s", "--no-walk") or "—"
            last_commit_time = _git("log", "-1", "--format=%ar", "--no-walk") or ""

            # Count changes
            status_output = _git("status", "--porcelain") or ""
            lines = [l for l in status_output.splitlines() if l.strip()]
            staged = sum(1 for l in lines if l[0] != ' ' and l[0] != '?')
            unstaged = sum(1 for l in lines if len(l) > 1 and l[1] != ' ' and l[0] != '?')
            untracked = sum(1 for l in lines if l.startswith('??'))

            # Check ahead/behind
            ahead, behind = 0, 0
            tracking = _git("rev-parse", "--abbrev-ref", "@{upstream}")
            if tracking:
                ab = _git("rev-list", "--left-right", "--count", f"HEAD...@{{upstream}}")
                if ab:
                    parts = ab.split()
                    if len(parts) == 2:
                        ahead, behind = int(parts[0]), int(parts[1])

            return jsonify({
                "available": True,
                "branch": branch,
                "last_commit": last_commit,
                "last_commit_time": last_commit_time,
                "staged": staged,
                "unstaged": unstaged,
                "untracked": untracked,
                "total_changes": len(lines),
                "ahead": ahead,
                "behind": behind,
                "clean": len(lines) == 0 and ahead == 0,
            })
        except Exception as e:
            return jsonify({"available": False, "error": str(e)})

    @app.route("/api/git/sync", methods=["POST"])
    def api_git_sync():
        """Commit all changes and push to remote."""
        import shutil as _shutil

        data = request.json or {}
        message = data.get("message", "chore: sync from admin panel")

        steps = []

        def _run(cmd, label, timeout=15):
            """Run a git command, log it, and append to steps."""
            logger.info("[git-sync] %s: %s", label, " ".join(cmd))
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = (result.stdout or "").strip()
            err = (result.stderr or "").strip()
            ok = result.returncode == 0
            steps.append({
                "step": label,
                "ok": ok,
                "output": out or err or None,
            })
            if ok:
                logger.info("[git-sync] %s: OK%s", label, f" — {out}" if out else "")
            else:
                logger.warning("[git-sync] %s: FAILED (rc=%d) — %s", label, result.returncode, err)
            return result

        try:
            # Pre-flight: is git installed?
            if not _shutil.which("git"):
                logger.error("[git-sync] git not found on PATH")
                return jsonify({
                    "success": False,
                    "error": "git is not installed",
                    "hint": "Install git: https://git-scm.com/downloads",
                    "steps": steps,
                })

            # Pre-flight: is this a git repo?
            result = _run(["git", "rev-parse", "--is-inside-work-tree"], "check repo")
            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": "Not a git repository",
                    "steps": steps,
                })

            # Pre-flight: is a remote configured?
            result = _run(["git", "remote", "-v"], "check remote")
            if not result.stdout.strip():
                return jsonify({
                    "success": False,
                    "error": "No git remote configured — run: git remote add origin <url>",
                    "steps": steps,
                })

            # Step 1: Stage everything so stash captures it all
            _run(["git", "add", "-A"], "git add")

            # Check if there's anything to sync
            result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            has_local_changes = result.returncode != 0

            if not has_local_changes:
                logger.info("[git-sync] Nothing new to commit — will still pull/push")

            # Step 2: Stash our changes (so working tree is clean for pull)
            result = _run(
                ["git", "stash", "push", "-m", "admin-sync-temp"],
                "git stash",
            )
            stashed = result.returncode == 0 and "No local changes" not in result.stdout

            # Step 3: Pull latest from remote (clean working tree → always works)
            result = _run(["git", "pull", "--ff"], "git pull", timeout=30)
            pull_ok = result.returncode == 0

            if not pull_ok:
                # If pull fails even with clean tree, try merge strategy
                logger.warning("[git-sync] Fast-forward pull failed, trying merge")
                result = _run(
                    ["git", "pull", "--no-rebase", "-X", "theirs"],
                    "git pull (merge)",
                    timeout=30,
                )
                pull_ok = result.returncode == 0
                if not pull_ok:
                    # Abort merge if in progress
                    _run(["git", "merge", "--abort"], "merge abort")
                    # Recover stash
                    if stashed:
                        _run(["git", "stash", "pop"], "stash recover")
                    return jsonify({
                        "success": False,
                        "error": "Could not pull remote changes. Check git status manually.",
                        "steps": steps,
                    })

            # Step 4: Re-apply our changes on top of latest
            if stashed:
                result = _run(["git", "stash", "pop"], "git stash pop")
                if result.returncode != 0:
                    # Stash pop conflict — auto-resolve: our changes win
                    logger.warning("[git-sync] Stash pop conflict — resolving with our version")
                    # Accept the partially-merged state (our files are there, just with conflict markers)
                    # Re-add everything to resolve
                    _run(["git", "checkout", "--theirs", "."], "resolve: keep ours")
                    _run(["git", "add", "-A"], "re-stage after resolve")
                    steps.append({
                        "step": "conflict resolved",
                        "ok": True,
                        "output": "Auto-resolved in favor of local changes",
                    })

            # Step 5: Stage and commit
            _run(["git", "add", "-A"], "git add (final)")
            
            # Check if there's still something to commit (pull might have already included our changes)
            result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Nothing new to commit — but we may still have unpushed commits
                logger.info("[git-sync] Nothing new to stage — checking if push needed")
                result = _run(["git", "push"], "git push", timeout=30)
                if result.returncode == 0:
                    pushed = result.stderr.strip() or result.stdout.strip()
                    if "Everything up-to-date" in pushed:
                        msg = "Already up to date (nothing to commit or push)"
                    else:
                        msg = "Pushed existing commits to remote"
                else:
                    return jsonify({
                        "success": False,
                        "error": result.stderr.strip() or "Push failed",
                        "hint": "Check authentication: gh auth status",
                        "steps": steps,
                    })
                # Auto-sync code to mirror if enabled
                _trigger_mirror_sync_bg("code-only")
                return jsonify({
                    "success": True,
                    "message": msg,
                    "steps": steps,
                })

            result = _run(["git", "commit", "-m", message], "git commit")
            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": result.stderr.strip() or "Commit failed",
                    "steps": steps,
                })

            # Step 6: Push (should be clean since we just pulled)
            result = _run(["git", "push"], "git push", timeout=30)
            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": result.stderr.strip() or "Push failed",
                    "hint": "Check authentication: gh auth status",
                    "steps": steps,
                })

            logger.info("[git-sync] ✓ Sync complete")

            # Auto-sync code to mirror if enabled
            _trigger_mirror_sync_bg("code-only")

            return jsonify({
                "success": True,
                "message": "Committed and pushed successfully",
                "steps": steps,
            })
        except subprocess.TimeoutExpired as e:
            logger.error("[git-sync] Timeout: %s", e)
            return jsonify({
                "success": False,
                "error": f"Command timed out: {e}",
                "steps": steps,
            }), 504
        except Exception as e:
            logger.exception("[git-sync] Unexpected error")
            return jsonify({"success": False, "error": str(e), "steps": steps}), 500

    # ─── Mirror API Endpoints ─────────────────────────────────────
    # These call CLI commands via subprocess (same pattern as test email, git sync, etc.)

    @app.route("/api/mirror/status", methods=["GET"])
    def api_mirror_status():
        """Get mirror status via CLI."""
        try:
            result = subprocess.run(
                ["python", "-m", "src.main", "mirror-status", "--json"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=15,
                env=_fresh_env(),
            )
            if result.returncode == 0:
                import json as _json
                return jsonify(_json.loads(result.stdout))
            return jsonify({"enabled": False, "error": result.stderr.strip()})
        except Exception as e:
            return jsonify({"enabled": False, "error": str(e)})

    @app.route("/api/mirror/sync/stream")
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

        def generate():
            proc = subprocess.Popen(
                cmd,
                cwd=str(project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_fresh_env(),
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
                    import json as _json
                    yield f"data: {_json.dumps({'step': 'error', 'status': 'failed', 'error': stderr_out.strip()})}\n\n"
            except Exception as e:
                import json as _json
                yield f"data: {_json.dumps({'step': 'error', 'status': 'failed', 'error': str(e)})}\n\n"
            finally:
                proc.kill() if proc.poll() is None else None

        return app.response_class(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.route("/api/mirror/clean/stream")
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

        def generate():
            proc = subprocess.Popen(
                cmd,
                cwd=str(project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_fresh_env(),
            )
            try:
                for line in proc.stdout:
                    line = line.strip()
                    if line:
                        yield f"data: {line}\n\n"
                proc.wait(timeout=120)
                stderr_out = proc.stderr.read()
                if stderr_out and proc.returncode != 0:
                    import json as _json
                    yield f"data: {_json.dumps({'step': 'error', 'status': 'failed', 'error': stderr_out.strip()})}\n\n"
            except Exception as e:
                import json as _json
                yield f"data: {_json.dumps({'step': 'error', 'status': 'failed', 'error': str(e)})}\n\n"
            finally:
                proc.kill() if proc.poll() is None else None

        return app.response_class(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Legacy endpoints (kept for backward compat / simple calls)
    @app.route("/api/mirror/sync", methods=["POST"])
    def api_mirror_sync():
        """Run full mirror sync (non-streaming fallback)."""
        try:
            result = subprocess.run(
                ["python", "-m", "src.main", "mirror-sync"],
                cwd=str(project_root), capture_output=True, text=True,
                timeout=120, env=_fresh_env(),
            )
            combined = (result.stdout or "") + (result.stderr or "")
            return jsonify({"success": result.returncode == 0, "output": combined.strip()})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/mirror/sync/code", methods=["POST"])
    def api_mirror_sync_code():
        """Run code-only sync (non-streaming fallback)."""
        try:
            result = subprocess.run(
                ["python", "-m", "src.main", "mirror-sync", "--code-only"],
                cwd=str(project_root), capture_output=True, text=True,
                timeout=120, env=_fresh_env(),
            )
            combined = (result.stdout or "") + (result.stderr or "")
            return jsonify({"success": result.returncode == 0, "output": combined.strip()})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/mirror/sync/secrets", methods=["POST"])
    def api_mirror_sync_secrets():
        """Run secrets-only sync (non-streaming fallback)."""
        try:
            result = subprocess.run(
                ["python", "-m", "src.main", "mirror-sync", "--secrets-only"],
                cwd=str(project_root), capture_output=True, text=True,
                timeout=120, env=_fresh_env(),
            )
            combined = (result.stdout or "") + (result.stderr or "")
            return jsonify({"success": result.returncode == 0, "output": combined.strip()})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

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
