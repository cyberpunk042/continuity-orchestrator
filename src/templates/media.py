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
      1. Cloudflare tunnel detection (CLOUDFLARE_TUNNEL_TOKEN)
      2. GITHUB_REPOSITORY → GitHub Pages URL
      3. None — cannot resolve

    Returns the base URL without trailing slash, or None.
    """
    # 1. Cloudflare tunnel detection
    tunnel_url = _detect_cloudflare_tunnel_url()
    if tunnel_url:
        return tunnel_url.rstrip("/")

    # 2. GitHub Pages
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo and "/" in repo:
        owner, repo_name = repo.split("/", 1)
        return f"https://{owner}.github.io/{repo_name}"

    # 3. Cannot resolve
    return None


def _detect_cloudflare_tunnel_url() -> Optional[str]:
    """
    Detect the public URL of a Cloudflare tunnel from the tunnel token.

    Decodes CLOUDFLARE_TUNNEL_TOKEN (base64 JSON: {a: account_id, t: tunnel_id,
    s: secret}) and queries the Cloudflare API for the tunnel's configured
    hostname in its ingress rules.
    """
    tunnel_token = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "").strip()
    if not tunnel_token:
        return None

    try:
        # Decode tunnel token: base64 → JSON {a: account_id, t: tunnel_id, s: secret}
        padded = tunnel_token + "=" * (-len(tunnel_token) % 4)
        token_data = json.loads(base64.b64decode(padded))

        account_id = token_data.get("a")
        tunnel_id = token_data.get("t")
        tunnel_secret = token_data.get("s")

        if not account_id or not tunnel_id:
            logger.warning("Cloudflare tunnel token missing account_id or tunnel_id")
            return None

        return _query_cloudflare_tunnel_hostname(
            account_id, tunnel_id, tunnel_secret
        )

    except Exception as e:
        logger.warning(f"Failed to decode Cloudflare tunnel token: {e}")
        return None


def _query_cloudflare_tunnel_hostname(
    account_id: str,
    tunnel_id: str,
    tunnel_secret: str,
) -> Optional[str]:
    """
    Query Cloudflare API for a tunnel's configured public hostname.

    GET /accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations
    → extract first hostname from ingress rules.
    """
    import urllib.request
    import urllib.error

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        f"/cfd_tunnel/{tunnel_id}/configurations"
    )

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {tunnel_secret}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        if not data.get("success"):
            errors = data.get("errors", [])
            logger.debug(f"Cloudflare tunnel API: {errors}")
            return None

        # Extract hostname from ingress rules
        config = data.get("result", {}).get("config", {})
        ingress = config.get("ingress", [])

        for rule in ingress:
            hostname = rule.get("hostname", "").strip()
            if hostname:
                return f"https://{hostname}"

        logger.debug("Cloudflare tunnel has no hostname in ingress rules")
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
