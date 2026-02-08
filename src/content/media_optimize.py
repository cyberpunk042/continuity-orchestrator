"""
Media Optimizer — resize and convert images before encryption.

Reduces image file sizes by:
1. Resizing to a max dimension (default 2048px)
2. Stripping alpha channel when not needed (RGBA → RGB)
3. Converting to WebP (best size/quality) or JPEG (wide compat)

The original bytes go in, optimized bytes come out.
The caller decides whether to encrypt and where to store.
"""

from __future__ import annotations

import io
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────

MAX_DIMENSION = 2048       # px — longest side
WEBP_QUALITY = 85          # lossy WebP quality
JPEG_QUALITY = 85          # fallback JPEG quality
TARGET_FORMAT = "WEBP"     # preferred output format

# Tier threshold: images above this after optimization go to large/
LARGE_THRESHOLD_BYTES = 2 * 1024 * 1024  # 2 MB


def optimize_image(
    data: bytes,
    mime_type: str,
    *,
    max_dimension: int = MAX_DIMENSION,
    quality: int = WEBP_QUALITY,
    target_format: str = TARGET_FORMAT,
) -> Tuple[bytes, str, str]:
    """
    Optimize an image: resize + convert.

    Args:
        data: Raw image bytes.
        mime_type: Original MIME type (e.g. "image/png").
        max_dimension: Max width or height in pixels.
        quality: Compression quality (1-100).
        target_format: Target format ("WEBP", "JPEG").

    Returns:
        Tuple of (optimized_bytes, new_mime_type, new_extension).
        If optimization fails or doesn't apply, returns the original
        data unchanged with original MIME type.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed — skipping image optimization")
        ext = _mime_to_ext(mime_type)
        return data, mime_type, ext

    # Only optimize raster images
    if not mime_type.startswith("image/") or mime_type in (
        "image/svg+xml",
        "image/gif",  # animated GIFs would break
    ):
        ext = _mime_to_ext(mime_type)
        return data, mime_type, ext

    try:
        img = Image.open(io.BytesIO(data))
        original_size = len(data)
        original_dims = img.size

        # ── Resize if over max dimension ─────────────────────
        w, h = img.size
        if max(w, h) > max_dimension:
            ratio = max_dimension / max(w, h)
            new_w = int(w * ratio)
            new_h = int(h * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            logger.debug(
                f"Resized: {w}x{h} → {new_w}x{new_h} "
                f"(max_dim={max_dimension})"
            )

        # ── Convert color mode ───────────────────────────────
        fmt = target_format.upper()

        if fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
            # JPEG doesn't support alpha — flatten to RGB
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
            img = bg
        elif fmt == "WEBP" and img.mode == "P":
            img = img.convert("RGBA")
        elif fmt in ("JPEG", "WEBP") and img.mode == "RGBA":
            # Check if alpha is actually used
            if not _has_meaningful_alpha(img):
                img = img.convert("RGB")

        # ── Encode ───────────────────────────────────────────
        buf = io.BytesIO()
        save_kwargs = {"quality": quality, "optimize": True}
        if fmt == "WEBP":
            save_kwargs["method"] = 4  # compression effort (0-6)
        img.save(buf, format=fmt, **save_kwargs)
        optimized = buf.getvalue()

        new_mime = f"image/{fmt.lower()}"
        new_ext = f".{fmt.lower()}"

        ratio = len(optimized) / original_size * 100
        logger.info(
            f"Optimized: {original_dims[0]}x{original_dims[1]} "
            f"({mime_type}) → {img.size[0]}x{img.size[1]} "
            f"({new_mime}): "
            f"{original_size:,} → {len(optimized):,} bytes "
            f"({ratio:.0f}%)"
        )

        return optimized, new_mime, new_ext

    except Exception as e:
        logger.warning(f"Image optimization failed: {e} — using original")
        ext = _mime_to_ext(mime_type)
        return data, mime_type, ext


def should_optimize(size_bytes: int, mime_type: str) -> bool:
    """Check if an image should be optimized before storing."""
    if not mime_type.startswith("image/"):
        return False
    if mime_type in ("image/svg+xml", "image/gif"):
        return False
    return size_bytes > LARGE_THRESHOLD_BYTES


def classify_storage(size_bytes: int) -> str:
    """
    Determine where an encrypted file should be stored.

    Returns:
        "inline" — base64 in article JSON (< 100KB)
        "git"    — content/media/{id}.enc, tracked in git (100KB–2MB)
        "large"  — content/media/large/{id}.enc, gitignored (> 2MB)
    """
    if size_bytes < 100 * 1024:
        return "inline"
    elif size_bytes <= LARGE_THRESHOLD_BYTES:
        return "git"
    else:
        return "large"


def _has_meaningful_alpha(img) -> bool:
    """Check if an RGBA image actually uses transparency."""
    if img.mode != "RGBA":
        return False
    alpha = img.split()[-1]
    extrema = alpha.getextrema()
    # If min alpha is 255, the entire image is fully opaque
    return extrema[0] < 255


def _mime_to_ext(mime_type: str) -> str:
    """Map MIME type to file extension."""
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
    }
    return mapping.get(mime_type, ".bin")
