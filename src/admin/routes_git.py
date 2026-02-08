"""
Admin API — Git management endpoints.

Blueprint: git_bp
Prefix: /api/git
"""

from __future__ import annotations

import logging
import subprocess

from flask import Blueprint, current_app, jsonify, request

from .helpers import fresh_env, trigger_mirror_sync_bg

logger = logging.getLogger(__name__)

git_bp = Blueprint("git", __name__)


def _project_root():
    return current_app.config["PROJECT_ROOT"]


@git_bp.route("/status", methods=["GET"])
def api_git_status():
    """Return git repo status for the dashboard."""
    import shutil as _shutil

    project_root = _project_root()

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


@git_bp.route("/fetch", methods=["POST"])
def api_git_fetch():
    """Fetch from remote and fast-forward pull if the tree is clean.

    Called periodically by the UI to keep the local repo up-to-date.
    Safe: never force-pushes, never commits, never touches dirty trees.
    """
    import shutil as _shutil

    project_root = _project_root()

    if not _shutil.which("git"):
        return jsonify({"fetched": False, "error": "git not installed"})

    def _git(*args, timeout=15):
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result

    try:
        # Pre-flight: is this a git repo with a remote?
        r = _git("rev-parse", "--is-inside-work-tree")
        if r.returncode != 0:
            return jsonify({"fetched": False, "error": "Not a git repo"})

        r = _git("remote")
        if r.returncode != 0 or not r.stdout.strip():
            return jsonify({"fetched": False, "error": "No remote configured"})

        # Step 1: Always fetch (lightweight, safe)
        r = _git("fetch", "--quiet", timeout=30)
        if r.returncode != 0:
            return jsonify({
                "fetched": False,
                "error": r.stderr.strip() or "Fetch failed",
            })

        # Step 2: Check if tree is clean
        r = _git("status", "--porcelain")
        dirty_lines = [l for l in (r.stdout or "").splitlines() if l.strip()]
        has_local_changes = len(dirty_lines) > 0

        # Step 3: Check ahead/behind after fetch
        ahead, behind = 0, 0
        tracking = _git("rev-parse", "--abbrev-ref", "@{upstream}")
        if tracking.returncode == 0 and tracking.stdout.strip():
            ab = _git("rev-list", "--left-right", "--count", "HEAD...@{upstream}")
            if ab.returncode == 0 and ab.stdout.strip():
                parts = ab.stdout.strip().split()
                if len(parts) == 2:
                    ahead, behind = int(parts[0]), int(parts[1])

        pulled = False
        pull_detail = None
        state = "clean"  # Will be overridden below

        # Step 4: Decide action based on tree state
        if has_local_changes:
            n = len(dirty_lines)
            state = "dirty"
            if behind > 0:
                pull_detail = f"↓{behind} new commit{'s' if behind > 1 else ''} on remote · {n} local change{'s' if n > 1 else ''} — Sync Now to merge"
            else:
                pull_detail = f"{n} local change{'s' if n > 1 else ''} · auto-pull paused"
        elif behind > 0 and ahead == 0:
            # Clean tree, behind remote → safe to fast-forward
            r = _git("pull", "--ff-only", timeout=30)
            if r.returncode == 0:
                pulled = True
                state = "pulled"
                pull_detail = f"Auto-pulled {behind} commit{'s' if behind > 1 else ''} from remote"
                logger.info("[git-fetch] %s", pull_detail)
                behind = 0
            else:
                state = "diverged"
                pull_detail = "Histories diverged — Sync Now to resolve"
                logger.warning("[git-fetch] FF pull failed: %s", r.stderr.strip())
        elif ahead > 0:
            state = "ahead"
            pull_detail = f"↑{ahead} unpushed commit{'s' if ahead > 1 else ''} — Sync Now to push"
        else:
            state = "clean"
            pull_detail = "Up to date with remote"

        return jsonify({
            "fetched": True,
            "pulled": pulled,
            "state": state,
            "ahead": ahead,
            "behind": behind,
            "has_local_changes": has_local_changes,
            "local_changes_count": len(dirty_lines),
            "detail": pull_detail,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"fetched": False, "error": "Fetch timed out"}), 504
    except Exception as e:
        logger.exception("[git-fetch] Error")
        return jsonify({"fetched": False, "error": str(e)}), 500


@git_bp.route("/sync", methods=["POST"])
def api_git_sync():
    """Commit all changes and push to remote."""
    import shutil as _shutil

    project_root = _project_root()
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

    def _trigger_bg(mode="code-only"):
        return trigger_mirror_sync_bg(project_root, mode)

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
            result = _run(["git", "push"], "git push", timeout=120)
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
            # Only trigger mirror sync if something was actually pushed
            mirror_triggered = False
            if "Everything up-to-date" not in (pushed or ""):
                mirror_triggered = _trigger_bg("code-only")
            return jsonify({
                "success": True,
                "message": msg,
                "mirror_sync_triggered": mirror_triggered,
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
        result = _run(["git", "push"], "git push", timeout=120)
        if result.returncode != 0:
            return jsonify({
                "success": False,
                "error": result.stderr.strip() or "Push failed",
                "hint": "Check authentication: gh auth status",
                "steps": steps,
            })

        logger.info("[git-sync] ✓ Sync complete")

        # Auto-sync code to mirror if enabled
        mirror_triggered = _trigger_bg("code-only")

        return jsonify({
            "success": True,
            "message": "Committed and pushed successfully",
            "mirror_sync_triggered": mirror_triggered,
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
