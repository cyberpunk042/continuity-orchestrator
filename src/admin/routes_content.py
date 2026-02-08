"""
Admin API — Content management endpoints.

Blueprint: content_bp
Prefix: /api/content
Routes:
    GET  /api/content/articles                  # List all articles
    GET  /api/content/articles/<slug>            # Get article content (decrypted)
    POST /api/content/articles/<slug>            # Save article content
    DELETE /api/content/articles/<slug>          # Delete article
    POST /api/content/articles/<slug>/encrypt    # Encrypt this article
    POST /api/content/articles/<slug>/decrypt    # Decrypt this article
    GET  /api/content/encryption-status          # Key availability
    POST /api/content/keygen                     # Generate new key
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

content_bp = Blueprint("content", __name__)

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    return current_app.config["PROJECT_ROOT"]


def _articles_dir() -> Path:
    return _project_root() / "content" / "articles"


# ── Helpers ──────────────────────────────────────────────────────


def _load_manifest():
    """Load the content manifest (returns None on error)."""
    try:
        from ..site.manifest import ContentManifest
        return ContentManifest.load()
    except Exception:
        return None


def _manifest_path() -> Path:
    return _project_root() / "content" / "manifest.yaml"


def _update_manifest_entry(slug: str, metadata: dict):
    """Update or insert an article entry in manifest.yaml."""
    import yaml

    manifest_file = _manifest_path()
    if manifest_file.exists():
        data = yaml.safe_load(manifest_file.read_text(encoding="utf-8")) or {}
    else:
        data = {"version": 1, "articles": [], "defaults": {"visibility": {"min_stage": "FULL"}}}

    articles = data.setdefault("articles", [])

    # Find existing entry
    entry = None
    for a in articles:
        if a.get("slug") == slug:
            entry = a
            break

    if entry is None:
        entry = {"slug": slug}
        articles.append(entry)

    # Update visibility
    vis = entry.setdefault("visibility", {})
    if "min_stage" in metadata:
        vis["min_stage"] = metadata["min_stage"]
    if "include_in_nav" in metadata:
        vis["include_in_nav"] = metadata["include_in_nav"]
    if "pin_to_top" in metadata:
        vis["pin_to_top"] = metadata["pin_to_top"]

    manifest_file.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    logger.info(f"Updated manifest entry for '{slug}': {vis}")


def _article_meta(slug: str, data: dict, manifest) -> dict:
    """Build metadata dict for an article."""
    from ..content.crypto import is_encrypted

    encrypted = is_encrypted(data)

    # Title from content (if not encrypted, or if we can't read it)
    title = slug.replace("_", " ").title()
    if not encrypted:
        for block in data.get("blocks", []):
            if block.get("type") == "header":
                title = block.get("data", {}).get("text", title)
                break

    meta = {
        "slug": slug,
        "title": title,
        "encrypted": encrypted,
    }

    # Manifest data
    if manifest:
        entry = manifest.get_article(slug)
        if entry:
            meta["min_stage"] = entry.visibility.min_stage
            meta["include_in_nav"] = entry.visibility.include_in_nav
            meta["description"] = entry.meta.description
            meta["pin_to_top"] = entry.visibility.pin_to_top
        else:
            meta["min_stage"] = None
            meta["include_in_nav"] = True
            meta["description"] = None
            meta["pin_to_top"] = False
    else:
        meta["min_stage"] = None
        meta["include_in_nav"] = True
        meta["description"] = None
        meta["pin_to_top"] = False

    return meta


# ── Routes ───────────────────────────────────────────────────────


@content_bp.route("/articles", methods=["GET"])
def api_list_articles():
    """List all articles with metadata."""
    from ..content.crypto import get_encryption_key, is_encrypted

    articles_dir = _articles_dir()
    manifest = _load_manifest()
    key_available = get_encryption_key() is not None

    articles = []
    if articles_dir.exists():
        for path in sorted(articles_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                meta = _article_meta(path.stem, data, manifest)

                # If encrypted and key is available, try to get real title
                if meta["encrypted"] and key_available:
                    try:
                        from ..content.crypto import decrypt_content, get_encryption_key
                        key = get_encryption_key()
                        content = decrypt_content(data, key)
                        for block in content.get("blocks", []):
                            if block.get("type") == "header":
                                meta["title"] = block.get("data", {}).get("text", meta["title"])
                                break
                    except Exception:
                        pass

                articles.append(meta)
            except Exception as e:
                logger.warning(f"Failed to read article {path.stem}: {e}")
                continue

    return jsonify({
        "articles": articles,
        "encryption_available": key_available,
    })


@content_bp.route("/articles/<slug>", methods=["GET"])
def api_get_article(slug: str):
    """Get article content (decrypted if encrypted and key available)."""
    from ..content.crypto import get_encryption_key, is_encrypted, decrypt_content

    path = _articles_dir() / f"{slug}.json"
    if not path.exists():
        return jsonify({"error": "Article not found"}), 404

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return jsonify({"error": f"Failed to read article: {e}"}), 500

    encrypted = is_encrypted(data)
    content = data

    if encrypted:
        key = get_encryption_key()
        if not key:
            return jsonify({
                "slug": slug,
                "encrypted": True,
                "error": "Encryption key not available — cannot decrypt",
            }), 200

        try:
            content = decrypt_content(data, key)
        except Exception as e:
            return jsonify({
                "slug": slug,
                "encrypted": True,
                "error": f"Decryption failed: {e}",
            }), 500

    # Extract title
    title = slug.replace("_", " ").title()
    for block in content.get("blocks", []):
        if block.get("type") == "header":
            title = block.get("data", {}).get("text", title)
            break

    # Manifest metadata
    manifest = _load_manifest()
    manifest_entry = None
    if manifest:
        entry = manifest.get_article(slug)
        if entry:
            manifest_entry = {
                "min_stage": entry.visibility.min_stage,
                "include_in_nav": entry.visibility.include_in_nav,
                "pin_to_top": entry.visibility.pin_to_top,
                "description": entry.meta.description,
            }

    return jsonify({
        "slug": slug,
        "title": title,
        "encrypted": encrypted,
        "content": content,
        "manifest_entry": manifest_entry,
    })


@content_bp.route("/articles/<slug>", methods=["POST"])
def api_save_article(slug: str):
    """Save article content (optionally encrypting)."""
    from ..content.crypto import encrypt_content, get_encryption_key, is_encrypted

    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    content = body.get("content")
    encrypt = body.get("encrypt", False)

    if not content or not isinstance(content, dict):
        return jsonify({"error": "Missing or invalid 'content' field"}), 400

    articles_dir = _articles_dir()
    articles_dir.mkdir(parents=True, exist_ok=True)

    data_to_write = content

    if encrypt:
        key = get_encryption_key()
        if not key:
            return jsonify({"error": "Cannot encrypt — CONTENT_ENCRYPTION_KEY not set"}), 400
        data_to_write = encrypt_content(content, key)

    path = articles_dir / f"{slug}.json"
    path.write_text(
        json.dumps(data_to_write, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Update manifest metadata if provided
    metadata = body.get("metadata")
    if metadata:
        _update_manifest_entry(slug, metadata)

    return jsonify({
        "success": True,
        "slug": slug,
        "encrypted": encrypt,
    })


@content_bp.route("/articles/<slug>", methods=["DELETE"])
def api_delete_article(slug: str):
    """Delete an article file."""
    path = _articles_dir() / f"{slug}.json"
    if not path.exists():
        return jsonify({"error": "Article not found"}), 404

    path.unlink()
    return jsonify({"success": True, "slug": slug})


@content_bp.route("/articles/<slug>/encrypt", methods=["POST"])
def api_encrypt_article(slug: str):
    """Encrypt a plaintext article in-place."""
    from ..content.crypto import encrypt_content, get_encryption_key, is_encrypted

    path = _articles_dir() / f"{slug}.json"
    if not path.exists():
        return jsonify({"error": "Article not found"}), 404

    key = get_encryption_key()
    if not key:
        return jsonify({"error": "CONTENT_ENCRYPTION_KEY not set"}), 400

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return jsonify({"error": f"Failed to read: {e}"}), 500

    if is_encrypted(data):
        return jsonify({"error": "Article is already encrypted"}), 400

    envelope = encrypt_content(data, key)
    path.write_text(
        json.dumps(envelope, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return jsonify({"success": True, "slug": slug, "encrypted": True})


@content_bp.route("/articles/<slug>/decrypt", methods=["POST"])
def api_decrypt_article(slug: str):
    """Decrypt an encrypted article and store as plaintext."""
    from ..content.crypto import decrypt_content, get_encryption_key, is_encrypted

    path = _articles_dir() / f"{slug}.json"
    if not path.exists():
        return jsonify({"error": "Article not found"}), 404

    key = get_encryption_key()
    if not key:
        return jsonify({"error": "CONTENT_ENCRYPTION_KEY not set"}), 400

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return jsonify({"error": f"Failed to read: {e}"}), 500

    if not is_encrypted(data):
        return jsonify({"error": "Article is already plaintext"}), 400

    try:
        content = decrypt_content(data, key)
    except Exception as e:
        return jsonify({"error": f"Decryption failed: {e}"}), 500

    path.write_text(
        json.dumps(content, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return jsonify({"success": True, "slug": slug, "encrypted": False})


@content_bp.route("/encryption-status", methods=["GET"])
def api_encryption_status():
    """Check if CONTENT_ENCRYPTION_KEY is configured."""
    from ..content.crypto import get_encryption_key

    key = get_encryption_key()
    return jsonify({
        "key_configured": key is not None,
    })


@content_bp.route("/keygen", methods=["POST"])
def api_keygen():
    """Generate a new encryption key (does NOT save it)."""
    from ..content.crypto import generate_key

    key = generate_key()
    return jsonify({"key": key})
