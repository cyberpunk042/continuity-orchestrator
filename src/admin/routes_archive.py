"""
Admin API — Internet Archive endpoints.

Blueprint: archive_bp
Prefix: /api/archive
"""

from __future__ import annotations

import logging
import os
import subprocess

from flask import Blueprint, current_app, jsonify, request

archive_bp = Blueprint("archive", __name__)
logger = logging.getLogger(__name__)


def _project_root():
    return current_app.config["PROJECT_ROOT"]


@archive_bp.route("", methods=["POST"])
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
    project_root = _project_root()
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


@archive_bp.route("/check", methods=["POST"])
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
    project_root = _project_root()
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
