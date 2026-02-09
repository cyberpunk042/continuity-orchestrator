"""
Media Optimizer — resize/convert images, compress video/audio before storage.

Image pipeline:
1. Resize to a max dimension (default 2048px)
2. Strip alpha channel when not needed (RGBA → RGB)
3. Convert to WebP (best size/quality) or JPEG (wide compat)

Video pipeline (requires ffmpeg):
1. Re-encode to H.264 (baseline) + AAC in MP4 container
2. Cap resolution to 1080p
3. Cap video bitrate to 2 Mbps, audio to 128 kbps

Audio pipeline (requires ffmpeg):
1. Convert to AAC in M4A container
2. Cap bitrate to 128 kbps

The original bytes go in, optimized bytes come out.
The caller decides whether to encrypt and where to store.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────

MAX_DIMENSION = 2048       # px — longest side (images)
WEBP_QUALITY = 85          # lossy WebP quality
JPEG_QUALITY = 85          # fallback JPEG quality
TARGET_FORMAT = "WEBP"     # preferred image output format

# Video defaults
VIDEO_MAX_HEIGHT = 1080    # px — max vertical resolution
VIDEO_BITRATE = "2M"       # video bitrate cap
AUDIO_BITRATE = "128k"     # audio bitrate cap
VIDEO_CRF = 28             # H.264 constant rate factor (18=high, 28=low)

# Tier thresholds
LARGE_THRESHOLD_BYTES = 2 * 1024 * 1024  # 2 MB — above this → large/ tier
IMAGE_OPTIMIZE_THRESHOLD = 100 * 1024     # 100 KB — optimize images above this


# ── Image optimization ───────────────────────────────────────


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

        pct = len(optimized) / original_size * 100
        logger.info(
            f"Optimized: {original_dims[0]}x{original_dims[1]} "
            f"({mime_type}) → {img.size[0]}x{img.size[1]} "
            f"({new_mime}): "
            f"{original_size:,} → {len(optimized):,} bytes "
            f"({pct:.0f}%)"
        )

        return optimized, new_mime, new_ext

    except Exception as e:
        logger.warning(f"Image optimization failed: {e} — using original")
        ext = _mime_to_ext(mime_type)
        return data, mime_type, ext


# ── Video / Audio optimization ───────────────────────────────


def _ffmpeg_available() -> bool:
    """Check if ffmpeg is on PATH."""
    return shutil.which("ffmpeg") is not None


def optimize_video(
    data: bytes,
    mime_type: str,
    *,
    max_height: int = VIDEO_MAX_HEIGHT,
    video_bitrate: str = VIDEO_BITRATE,
    audio_bitrate: str = AUDIO_BITRATE,
    crf: int = VIDEO_CRF,
) -> Tuple[bytes, str, str]:
    """
    Optimize a video: re-encode to H.264/AAC MP4, cap resolution & bitrate.

    Args:
        data: Raw video bytes.
        mime_type: Original MIME type.
        max_height: Max vertical resolution in pixels.
        video_bitrate: Max video bitrate (ffmpeg format, e.g. "2M").
        audio_bitrate: Audio bitrate target (e.g. "128k").
        crf: H.264 constant rate factor (lower = higher quality).

    Returns:
        Tuple of (optimized_bytes, new_mime_type, new_extension).
        If ffmpeg is unavailable or optimization fails, returns original.
    """
    if not _ffmpeg_available():
        logger.info("ffmpeg not available — storing video as-is")
        ext = _ext_for_video_mime(mime_type)
        return data, mime_type, ext

    original_size = len(data)
    tmpdir = tempfile.mkdtemp(prefix="media_opt_")

    try:
        # Detect input extension from MIME
        in_ext = _ext_for_video_mime(mime_type)
        in_path = Path(tmpdir) / f"input{in_ext}"
        out_path = Path(tmpdir) / "output.mp4"

        in_path.write_bytes(data)

        # Probe input to decide if scaling is needed
        scale_filter = _build_scale_filter(in_path, max_height)

        # Build ffmpeg command
        cmd = [
            "ffmpeg", "-y",
            "-i", str(in_path),
            # Video: H.264 baseline, CRF with bitrate cap
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(crf),
            "-maxrate", video_bitrate,
            "-bufsize", "4M",
            "-profile:v", "high",
            "-level", "4.1",
            "-pix_fmt", "yuv420p",
            # Audio: AAC
            "-c:a", "aac",
            "-b:a", audio_bitrate,
            # Container
            "-movflags", "+faststart",
        ]

        # Add scale filter if needed
        if scale_filter:
            cmd.extend(["-vf", scale_filter])

        cmd.append(str(out_path))

        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=300,
        )

        if proc.returncode != 0:
            logger.warning(
                f"ffmpeg video optimization failed (rc={proc.returncode}): "
                f"{proc.stderr[-500:]}"
            )
            return data, mime_type, in_ext

        if not out_path.exists():
            logger.warning("ffmpeg produced no output file")
            return data, mime_type, in_ext

        optimized = out_path.read_bytes()
        new_mime = "video/mp4"
        new_ext = ".mp4"

        # Only use optimized version if it's actually smaller
        if len(optimized) >= original_size:
            logger.info(
                f"Video optimization did not reduce size "
                f"({original_size:,} → {len(optimized):,}), keeping original"
            )
            return data, mime_type, in_ext

        pct = len(optimized) / original_size * 100
        logger.info(
            f"Video optimized: {original_size:,} → {len(optimized):,} bytes "
            f"({pct:.0f}%) [{mime_type} → {new_mime}]"
        )

        return optimized, new_mime, new_ext

    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg video optimization timed out (300s)")
        ext = _ext_for_video_mime(mime_type)
        return data, mime_type, ext
    except Exception as e:
        logger.warning(f"Video optimization error: {e}")
        ext = _ext_for_video_mime(mime_type)
        return data, mime_type, ext
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def optimize_audio(
    data: bytes,
    mime_type: str,
    *,
    bitrate: str = AUDIO_BITRATE,
) -> Tuple[bytes, str, str]:
    """
    Optimize audio: re-encode to AAC in M4A container.

    Args:
        data: Raw audio bytes.
        mime_type: Original MIME type.
        bitrate: Target audio bitrate (e.g. "128k").

    Returns:
        Tuple of (optimized_bytes, new_mime_type, new_extension).
        If ffmpeg is unavailable or fails, returns original.
    """
    if not _ffmpeg_available():
        logger.info("ffmpeg not available — storing audio as-is")
        ext = _ext_for_audio_mime(mime_type)
        return data, mime_type, ext

    original_size = len(data)
    tmpdir = tempfile.mkdtemp(prefix="media_opt_")

    try:
        in_ext = _ext_for_audio_mime(mime_type)
        in_path = Path(tmpdir) / f"input{in_ext}"
        out_path = Path(tmpdir) / "output.m4a"

        in_path.write_bytes(data)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(in_path),
            "-c:a", "aac",
            "-b:a", bitrate,
            "-movflags", "+faststart",
            str(out_path),
        ]

        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120,
        )

        if proc.returncode != 0:
            logger.warning(
                f"ffmpeg audio optimization failed (rc={proc.returncode}): "
                f"{proc.stderr[-500:]}"
            )
            return data, mime_type, in_ext

        if not out_path.exists():
            logger.warning("ffmpeg produced no output file")
            return data, mime_type, in_ext

        optimized = out_path.read_bytes()
        new_mime = "audio/mp4"
        new_ext = ".m4a"

        # Only use optimized if smaller
        if len(optimized) >= original_size:
            logger.info(
                f"Audio optimization did not reduce size "
                f"({original_size:,} → {len(optimized):,}), keeping original"
            )
            return data, mime_type, in_ext

        pct = len(optimized) / original_size * 100
        logger.info(
            f"Audio optimized: {original_size:,} → {len(optimized):,} bytes "
            f"({pct:.0f}%) [{mime_type} → {new_mime}]"
        )

        return optimized, new_mime, new_ext

    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg audio optimization timed out (120s)")
        ext = _ext_for_audio_mime(mime_type)
        return data, mime_type, ext
    except Exception as e:
        logger.warning(f"Audio optimization error: {e}")
        ext = _ext_for_audio_mime(mime_type)
        return data, mime_type, ext
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def optimize_media(
    data: bytes,
    mime_type: str,
) -> Tuple[bytes, str, str, bool]:
    """
    Universal optimization dispatcher — picks the right optimizer for any MIME type.

    Returns:
        Tuple of (optimized_bytes, new_mime_type, new_extension, was_optimized).
    """
    if should_optimize_image(len(data), mime_type):
        opt_data, opt_mime, opt_ext = optimize_image(data, mime_type)
        was_optimized = len(opt_data) < len(data)
        return opt_data, opt_mime, opt_ext, was_optimized

    if mime_type.startswith("video/"):
        opt_data, opt_mime, opt_ext = optimize_video(data, mime_type)
        was_optimized = len(opt_data) < len(data)
        return opt_data, opt_mime, opt_ext, was_optimized

    if mime_type.startswith("audio/"):
        opt_data, opt_mime, opt_ext = optimize_audio(data, mime_type)
        was_optimized = len(opt_data) < len(data)
        return opt_data, opt_mime, opt_ext, was_optimized

    # No optimization available for this type
    import mimetypes as mt
    ext = mt.guess_extension(mime_type) or ".bin"
    return data, mime_type, ext, False


# ── Decision helpers ─────────────────────────────────────────


def should_optimize_image(size_bytes: int, mime_type: str) -> bool:
    """Check if an image should be optimized before storing."""
    if not mime_type.startswith("image/"):
        return False
    if mime_type in ("image/svg+xml", "image/gif"):
        return False
    # Optimize any image above 100 KB
    return size_bytes > IMAGE_OPTIMIZE_THRESHOLD


# Keep old name for backwards compatibility
should_optimize = should_optimize_image


def classify_storage(size_bytes: int) -> str:
    """
    Determine where a media file should be stored.

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


# ── Internal helpers ─────────────────────────────────────────


def _has_meaningful_alpha(img) -> bool:
    """Check if an RGBA image actually uses transparency."""
    if img.mode != "RGBA":
        return False
    alpha = img.split()[-1]
    extrema = alpha.getextrema()
    # If min alpha is 255, the entire image is fully opaque
    return extrema[0] < 255


def _mime_to_ext(mime_type: str) -> str:
    """Map image MIME type to file extension."""
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


def _ext_for_video_mime(mime_type: str) -> str:
    """Map video MIME type to file extension."""
    mapping = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/x-msvideo": ".avi",
        "video/x-matroska": ".mkv",
        "video/ogg": ".ogv",
        "video/3gpp": ".3gp",
    }
    return mapping.get(mime_type, ".mp4")


def _ext_for_audio_mime(mime_type: str) -> str:
    """Map audio MIME type to file extension."""
    mapping = {
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/webm": ".weba",
        "audio/flac": ".flac",
        "audio/x-flac": ".flac",
    }
    return mapping.get(mime_type, ".m4a")


def _build_scale_filter(input_path: Path, max_height: int) -> Optional[str]:
    """Probe video dimensions and return an ffmpeg scale filter if needed."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=height",
                "-of", "csv=p=0",
                str(input_path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        height = int(result.stdout.strip())
        if height > max_height:
            # Scale down, keep aspect ratio, ensure even dimensions
            return f"scale=-2:{max_height}"
    except (ValueError, subprocess.TimeoutExpired, Exception) as e:
        logger.debug(f"Could not probe video dimensions: {e}")

    return None
