"""
Media Resolution — Shared utilities for resolving media URIs and rendering.

Used by:
  - tick.py: resolve media:// URIs to public URLs after template rendering
  - email_resend.py: convert ![](url) to <img> tags in HTML email
  - routes_messages.py: preview/send media handling
  - sms_twilio.py / x_twitter.py: strip media to text labels
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Regex to match ![alt](url) — non-greedy, handles all media types.
# The alt text prefix determines the media type:
#   (no prefix)     → image
#   "video: ..."    → video
#   "audio: ..."    → audio
#   "file: ..."     → file/attachment
MEDIA_MD_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

# Prefix for media:// URI references
MEDIA_URI_PREFIX = "media://"


# ── Public URL Resolution ────────────────────────────────────────────


def get_site_base_url() -> Optional[str]:
    """
    Determine the public base URL of the deployed site.

    Resolution priority:
      1. Cached Cloudflare tunnel hostname (process-level cache)
      2. Cloudflare tunnel detection (CLOUDFLARE_TUNNEL_TOKEN)
      3. GITHUB_REPOSITORY → GitHub Pages URL
      4. None — cannot resolve

    Returns the base URL without trailing slash, or None.
    """
    global _cached_tunnel_url

    # 1. Return in-memory cached value if available
    if _cached_tunnel_url:
        return _cached_tunnel_url

    # 2. Try disk cache (survives process restarts, shared across processes)
    disk_cached = _read_tunnel_cache()
    if disk_cached:
        _cached_tunnel_url = disk_cached
        logger.debug(f"Resolved site base URL (disk cache): {_cached_tunnel_url}")
        return _cached_tunnel_url

    # 3. Cloudflare tunnel detection via API
    tunnel_url = _detect_cloudflare_tunnel_url()
    if tunnel_url:
        _cached_tunnel_url = tunnel_url.rstrip("/")
        _write_tunnel_cache(_cached_tunnel_url)
        logger.info(f"Resolved site base URL (Cloudflare): {_cached_tunnel_url}")
        return _cached_tunnel_url

    # 3. GitHub Pages (fallback — media may NOT be served here)
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo and "/" in repo:
        owner, repo_name = repo.split("/", 1)
        gh_url = f"https://{owner}.github.io/{repo_name}"
        logger.warning(
            f"Cloudflare tunnel detection failed, falling back to GitHub Pages: "
            f"{gh_url} — media files may not be available at this URL"
        )
        return gh_url

    # 4. Cannot resolve
    logger.warning("Cannot determine site base URL — no tunnel, no GITHUB_REPOSITORY")
    return None


def _detect_cloudflare_tunnel_url() -> Optional[str]:
    """
    Detect the public URL of a Cloudflare tunnel from the tunnel token.

    Decodes CLOUDFLARE_TUNNEL_TOKEN (base64 JSON: {a: account_id, t: tunnel_id,
    s: secret}) and queries the Cloudflare API for the tunnel's configured
    hostname in its ingress rules.

    Uses CLOUDFLARE_API_TOKEN for API authentication (NOT the tunnel secret).
    Auto-refreshes the OAuth token on 401.
    """
    tunnel_token = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "").strip()
    if not tunnel_token:
        return None

    cf_api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not cf_api_token:
        logger.warning("CLOUDFLARE_API_TOKEN not set — cannot query tunnel hostname")
        return None

    try:
        # Decode tunnel token: base64 → JSON {a: account_id, t: tunnel_id, s: secret}
        padded = tunnel_token + "=" * (-len(tunnel_token) % 4)
        token_data = json.loads(base64.b64decode(padded))

        account_id = token_data.get("a")
        tunnel_id = token_data.get("t")

        if not account_id or not tunnel_id:
            logger.warning("Cloudflare tunnel token missing account_id or tunnel_id")
            return None

        hostname = _query_cloudflare_tunnel_hostname(
            account_id, tunnel_id, cf_api_token
        )

        # If 401, try refreshing the OAuth token and retry
        if hostname is None and _last_api_status == 401:
            try:
                from ..admin.routes_docker import _refresh_cf_api_token
                from pathlib import Path
                # Find project root from env or cwd
                project_root = Path(os.environ.get("PROJECT_ROOT", os.getcwd()))
                env_file = project_root / ".env"
                new_token = _refresh_cf_api_token(env_file=env_file)
                if new_token:
                    os.environ["CLOUDFLARE_API_TOKEN"] = new_token
                    hostname = _query_cloudflare_tunnel_hostname(
                        account_id, tunnel_id, new_token
                    )
            except ImportError:
                logger.debug("Cannot import refresh logic — skipping token refresh")

        return hostname

    except Exception as e:
        logger.warning(f"Failed to decode Cloudflare tunnel token: {e}")
        return None


# Track last API status for refresh logic
_last_api_status: int = 0

# Cache resolved tunnel hostname (in-memory + disk)
_cached_tunnel_url: Optional[str] = None

# Disk cache TTL: 1 hour — tunnel hostnames rarely change
_TUNNEL_CACHE_TTL = 3600


def _tunnel_cache_path() -> Path:
    """Path to the tunnel URL disk cache file."""
    root = Path(os.environ.get("PROJECT_ROOT", os.getcwd()))
    return root / "state" / ".tunnel_cache.json"


def _read_tunnel_cache() -> Optional[str]:
    """Read tunnel URL from disk cache if still fresh."""
    try:
        p = _tunnel_cache_path()
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        url = data.get("url", "").strip()
        ts = data.get("ts", 0)
        if url and (time.time() - ts) < _TUNNEL_CACHE_TTL:
            return url
    except Exception:
        pass
    return None


def _write_tunnel_cache(url: str) -> None:
    """Persist tunnel URL to disk cache."""
    try:
        p = _tunnel_cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"url": url, "ts": time.time()}))
    except Exception as e:
        logger.debug(f"Failed to write tunnel cache: {e}")


def _query_cloudflare_tunnel_hostname(
    account_id: str,
    tunnel_id: str,
    api_token: str,
) -> Optional[str]:
    """
    Query Cloudflare API for a tunnel's configured public hostname.

    GET /accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations
    → extract first hostname from ingress rules.
    """
    global _last_api_status
    import urllib.error
    import urllib.request

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        f"/cfd_tunnel/{tunnel_id}/configurations"
    )

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {api_token}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            _last_api_status = resp.status
            data = json.loads(resp.read())

        if not data.get("success"):
            errors = data.get("errors", [])
            logger.debug(f"Cloudflare tunnel API: {errors}")
            return None

        # Extract hostname from ingress rules
        config = (data.get("result") or {}).get("config") or {}
        ingress = config.get("ingress") or []

        for rule in ingress:
            hostname = rule.get("hostname", "").strip()
            if hostname:
                return f"https://{hostname}"

        logger.debug("Cloudflare tunnel has no hostname in ingress rules")
        return None

    except urllib.error.HTTPError as e:
        _last_api_status = e.code
        logger.debug(f"Cloudflare tunnel API HTTP {e.code}")
        return None
    except urllib.error.URLError as e:
        logger.debug(f"Cloudflare tunnel API unreachable: {e}")
        return None
    except Exception as e:
        logger.debug(f"Cloudflare tunnel hostname detection failed: {e}")
        return None


# ── Media URI Resolution ─────────────────────────────────────────────


def resolve_media_uris(text: str, stage: str = "") -> str:
    """
    Resolve media:// URIs in markdown to public URLs.

    For each ![alt](media://id):
      - Looks up media ID in manifest
      - Checks stage visibility (if stage provided)
      - Resolves to public URL: {base_url}/media/{original_name}
      - Falls back to stripping to text label if resolution fails

    Non-media:// URLs (data:, https://) pass through unchanged.

    Args:
        text: Markdown text potentially containing media:// URIs
        stage: Current escalation stage for visibility checks (optional)

    Returns:
        Text with media:// URIs resolved to public URLs.
    """
    # Quick check — skip work if no media:// URIs
    if MEDIA_URI_PREFIX not in text:
        return text

    # Lazy-load manifest and base URL only when needed
    base_url = get_site_base_url()
    manifest = _load_manifest()

    def _resolve(match: re.Match) -> str:
        alt = match.group(1)
        url = match.group(2)

        if not url.startswith(MEDIA_URI_PREFIX):
            return match.group(0)  # Not a media:// URI, pass through

        media_id = url[len(MEDIA_URI_PREFIX):]

        # No base URL → can't resolve, strip to label
        if not base_url:
            logger.warning(
                f"Cannot resolve media://{media_id} — no public URL configured. "
                f"Set CLOUDFLARE_TUNNEL_TOKEN or GITHUB_REPOSITORY."
            )
            return _to_label(alt)

        # Look up in manifest
        if manifest:
            entry = manifest.get(media_id)
            if entry:
                # Stage visibility check
                if stage and not entry.is_visible_at(stage):
                    logger.info(
                        f"Media '{media_id}' not visible at stage '{stage}', stripping"
                    )
                    return _to_label(alt)

                # Resolve to public URL
                public_url = f"{base_url}/media/{entry.original_name}"
                return f"![{alt}]({public_url})"
            else:
                logger.warning(f"Media '{media_id}' not found in manifest")
        else:
            logger.warning("No media manifest available")

        # If we can't find the entry in the manifest, we still try with the
        # media_id as filename (best effort — the site generator uses original_name)
        return _to_label(alt)

    return MEDIA_MD_RE.sub(_resolve, text)


def _load_manifest():
    """Load the media manifest, returning None on failure."""
    try:
        from ..content.media import MediaManifest
        return MediaManifest.load()
    except Exception as e:
        logger.warning(f"Failed to load media manifest: {e}")
        return None


def _to_label(alt: str) -> str:
    """Convert an alt text to a plain-text label."""
    alt = alt.strip()
    if alt.lower().startswith("video:"):
        name = alt[6:].strip() or "video"
        return f"[🎬 {name}]"
    elif alt.lower().startswith("audio:"):
        name = alt[6:].strip() or "audio"
        return f"[🎵 {name}]"
    elif alt.lower().startswith("file:"):
        name = alt[5:].strip() or "file"
        return f"[📎 {name}]"
    else:
        name = alt or "image"
        return f"[📸 {name}]"


# ── Media Markdown → HTML (for email) ────────────────────────────────


def media_md_to_html(text: str) -> str:
    """
    Convert markdown media syntax to email-safe HTML.

    Handles four media types based on alt-text prefix:
      ![caption](url)            → <img> tag
      ![video: caption](url)     → styled video link
      ![audio: caption](url)     → styled audio link
      ![file: filename](url)     → styled download link

    MUST be called BEFORE the general link regex to avoid ![text](url)
    being consumed by [text](url).
    """
    def _render(match: re.Match) -> str:
        alt = match.group(1).strip()
        url = match.group(2)

        if alt.lower().startswith("video:"):
            caption = alt[6:].strip() or "Video"
            return (
                f'<div style="margin:12px 0;padding:12px 16px;'
                f'background:#f1f5f9;border-radius:8px;border-left:4px solid #6366f1;">'
                f'<a href="{url}" style="color:#6366f1;text-decoration:none;font-weight:600;">'
                f'🎬 {caption}</a>'
                f'<div style="font-size:12px;color:#64748b;margin-top:4px;">'
                f'Video — click to view</div></div>'
            )
        elif alt.lower().startswith("audio:"):
            caption = alt[6:].strip() or "Audio"
            return (
                f'<div style="margin:12px 0;padding:12px 16px;'
                f'background:#f1f5f9;border-radius:8px;border-left:4px solid #8b5cf6;">'
                f'<a href="{url}" style="color:#8b5cf6;text-decoration:none;font-weight:600;">'
                f'🎵 {caption}</a>'
                f'<div style="font-size:12px;color:#64748b;margin-top:4px;">'
                f'Audio — click to listen</div></div>'
            )
        elif alt.lower().startswith("file:"):
            filename = alt[5:].strip() or "Attachment"
            return (
                f'<div style="margin:12px 0;padding:12px 16px;'
                f'background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;">'
                f'<a href="{url}" style="color:#6366f1;text-decoration:none;font-weight:600;">'
                f'📎 {filename}</a>'
                f'<div style="font-size:12px;color:#64748b;margin-top:4px;">'
                f'File attachment — click to download</div></div>'
            )
        else:
            # Image (default)
            alt_text = alt or "Image"
            return (
                f'<div style="margin:12px 0;text-align:center;">'
                f'<img src="{url}" alt="{alt_text}" '
                f'style="max-width:100%;height:auto;border-radius:8px;'
                f'border:1px solid #e2e8f0;">'
                + (f'<div style="font-size:12px;color:#64748b;margin-top:6px;'
                   f'font-style:italic;">{alt_text}</div>' if alt else '')
                + '</div>'
            )

    return MEDIA_MD_RE.sub(_render, text)


# ── Strip Media for Plaintext Adapters ───────────────────────────────


def strip_media_to_labels(text: str) -> str:
    """
    Replace markdown media references with plain-text labels.

    Used by SMS, X, and other adapters that cannot render media.
      ![caption](url)           → [📸 caption]
      ![video: cap](url)        → [🎬 cap]
      ![audio: cap](url)        → [🎵 cap]
      ![file: filename](url)    → [📎 filename]
    """
    def _label(match: re.Match) -> str:
        alt = match.group(1).strip()
        return _to_label(alt)

    return MEDIA_MD_RE.sub(_label, text)
