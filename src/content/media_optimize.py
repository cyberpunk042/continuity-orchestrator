"""
Media Optimizer — compress/convert all media types before storage.

Image pipeline:
1. Resize to a max dimension (default 2048px)
2. Strip alpha channel when not needed (RGBA → RGB)
3. Convert to WebP (best size/quality) or JPEG (wide compat)

Video pipeline (requires ffmpeg):
1. Re-encode to H.264 (high profile) + AAC in MP4 container
2. Cap resolution to 1080p, bitrate to 1.5 Mbps
3. Always try CRF-based re-encode for files > 10 MB

Audio pipeline (requires ffmpeg):
1. Convert to AAC in M4A container
2. Cap bitrate to 96 kbps

Text pipeline (CSV, JSON, XML, logs, markdown, etc.):
1. Gzip compress files > 100 KB
2. Stored as .gz, decompressed on serve

PDF pipeline (requires ghostscript):
1. Re-distill with /screen or /ebook quality
2. Only keeps result if smaller than original

The original bytes go in, optimized bytes come out.
The caller decides whether to encrypt and where to store.
"""

from __future__ import annotations

import gzip
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
VIDEO_BITRATE = "1500k"    # video bitrate cap (1.5 Mbps — plenty for web 1080p)
AUDIO_BITRATE = "96k"      # audio bitrate cap (96k AAC ≈ transparent for speech)
VIDEO_CRF = 28             # H.264 constant rate factor (18=high, 28=low)
VIDEO_SKIP_BELOW = 10 * 1024 * 1024  # don't bother optimizing videos under 10 MB

# Text/document compression
TEXT_COMPRESS_THRESHOLD = 100 * 1024  # 100 KB — gzip text files above this
COMPRESSIBLE_MIMES = {
    "text/plain", "text/csv", "text/html", "text/xml", "text/markdown",
    "text/tab-separated-values", "text/css", "text/javascript",
    "application/json", "application/xml", "application/ld+json",
    "application/x-ndjson", "application/sql",
}
COMPRESSIBLE_EXTENSIONS = {
    ".csv", ".json", ".xml", ".md", ".txt", ".log", ".sql",
    ".tsv", ".ndjson", ".jsonl", ".yml", ".yaml", ".toml",
    ".html", ".css", ".js", ".svg",
}

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

# Cache for hardware encoder detection
_hw_encoder_cache = {}

# Active ffmpeg process reference for cancellation
_active_ffmpeg_proc = None

# Optimization state for frontend polling
# { "status": "encoding"|"done"|"idle", "elapsed": float, "deadline": float,
#   "deadline_warning": bool, "progress": str, "encoder": str, "fps": str, "speed": str }
_optimization_state = {"status": "idle"}


def cancel_active_optimization() -> bool:
    """Kill the active ffmpeg process if one is running.

    Returns True if a process was killed, False otherwise.
    """
    global _active_ffmpeg_proc, _optimization_state
    if _active_ffmpeg_proc is not None and _active_ffmpeg_proc.poll() is None:
        _active_ffmpeg_proc.kill()
        try:
            _active_ffmpeg_proc.wait(timeout=5)
        except Exception:
            pass
        logger.info("Killed active ffmpeg process (user cancelled)")
        _active_ffmpeg_proc = None
        _optimization_state = {"status": "idle"}
        return True
    _active_ffmpeg_proc = None
    _optimization_state = {"status": "idle"}
    return False


def get_optimization_status() -> dict:
    """Return current optimization state for frontend polling."""
    return dict(_optimization_state)


def extend_optimization(extra_seconds: int = 300) -> dict:
    """Extend the current optimization deadline.

    Returns the new state.
    """
    if _optimization_state.get("status") != "encoding":
        return {"success": False, "message": "No active encoding"}

    old_deadline = _optimization_state.get("deadline", 0)
    _optimization_state["deadline"] = old_deadline + extra_seconds
    _optimization_state["deadline_warning"] = False
    logger.info(
        f"Optimization deadline extended by {extra_seconds}s "
        f"→ {_optimization_state['deadline']:.0f}s total"
    )
    return {
        "success": True,
        "message": f"Extended by {extra_seconds // 60} min",
        "new_deadline": _optimization_state["deadline"],
    }


def _parse_ffmpeg_progress(line: str) -> dict:
    """Extract progress info from an ffmpeg stderr line.

    Example: frame= 1234 fps=125 q=28.0 size= 5120kB time=00:01:23.45 bitrate= 500.0kbits/s speed=2.1x
    """
    import re
    info = {}
    m = re.search(r'fps=\s*(\S+)', line)
    if m:
        info['fps'] = m.group(1)
    m = re.search(r'speed=\s*(\S+)', line)
    if m:
        info['speed'] = m.group(1)
    m = re.search(r'time=\s*(\S+)', line)
    if m:
        info['time'] = m.group(1)
    m = re.search(r'frame=\s*(\d+)', line)
    if m:
        info['frame'] = int(m.group(1))
    m = re.search(r'size=\s*(\S+)', line)
    if m:
        info['size'] = m.group(1)
    return info


def _ffmpeg_available() -> bool:
    """Check if ffmpeg is on PATH."""
    return shutil.which("ffmpeg") is not None


def _detect_hw_encoder() -> Optional[str]:
    """Detect if NVIDIA NVENC is available for H.264 encoding.

    Tests by running a tiny encode — some systems have the encoder listed
    but it fails at runtime if no GPU is present or drivers are wrong.
    Result is cached for the process lifetime.
    """
    if "h264" in _hw_encoder_cache:
        return _hw_encoder_cache["h264"]

    _hw_encoder_cache["h264"] = None  # default: no hw encoder

    if not _ffmpeg_available():
        return None

    try:
        # Check if h264_nvenc is listed
        check = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True, text=True, timeout=5,
        )
        if "h264_nvenc" not in check.stdout:
            logger.debug("NVENC not listed in ffmpeg encoders")
            return None

        # Verify it actually works with a tiny test encode
        # (NVENC rejects very small resolutions, use 256x256)
        test = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1:r=30",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, timeout=10,
        )
        if test.returncode == 0:
            _hw_encoder_cache["h264"] = "h264_nvenc"
            logger.info("🚀 NVIDIA NVENC detected — will use GPU-accelerated encoding")
            return "h264_nvenc"
        else:
            logger.debug(f"NVENC test encode failed: {test.stderr[:200]}")
            return None

    except Exception as e:
        logger.debug(f"NVENC detection failed: {e}")
        return None


def _probe_media(file_path: Path) -> Optional[dict]:
    """Probe a media file for codec, resolution, bitrate info."""
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration,size,bit_rate",
                "-show_entries", "stream=codec_name,codec_type,width,height,bit_rate",
                "-of", "json",
                str(file_path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return None
        import json
        return json.loads(proc.stdout)
    except Exception as e:
        logger.debug(f"ffprobe failed: {e}")
        return None


def _needs_video_reencode(
    probe: dict,
    file_size: int,
    max_height: int = VIDEO_MAX_HEIGHT,
) -> tuple:
    """Decide whether a video needs re-encoding based on probe data.

    Philosophy: CRF-based re-encoding almost always reduces file size
    compared to source material (camera recordings, screen captures,
    editing exports). We ALWAYS try for files above VIDEO_SKIP_BELOW.
    The caller keeps the original if the result isn't smaller.

    Returns:
        (needs_reencode: bool, reason: str)
    """
    # Small files: not worth the CPU time
    if file_size < VIDEO_SKIP_BELOW:
        return False, f"file under {VIDEO_SKIP_BELOW // (1024*1024)} MB"

    streams = probe.get("streams", [])
    video_stream = None
    for s in streams:
        if s.get("codec_type") == "video" or (video_stream is None and "width" in s):
            video_stream = s

    if not video_stream:
        return False, "no video stream found"

    # Check resolution — must downscale
    height = video_stream.get("height", 0)
    if height > max_height:
        return True, f"resolution {height}p → downscale to {max_height}p"

    # For everything else: always try re-encoding.
    # CRF 28 + maxrate cap will almost certainly shrink camera/export footage.
    # The caller compares output size vs original and keeps whichever is smaller.
    fmt = probe.get("format", {})
    total_bitrate = int(fmt.get("bit_rate", 0))
    file_mb = file_size / (1024 * 1024)
    return True, (
        f"{file_mb:.0f} MB, {total_bitrate//1000}kbps → "
        f"re-encoding with CRF {VIDEO_CRF} + maxrate {VIDEO_BITRATE}"
    )


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
    Optimize a video: probe first, then re-encode only if needed.

    Smart pipeline:
    1. Probe input for codec, resolution, bitrate
    2. If already H.264/AAC at ≤1080p and ≤2.5Mbps → skip (return as-is)
    3. If codec is fine but container is wrong → fast stream copy
    4. Otherwise → full re-encode with H.264 CRF + bitrate cap

    Returns:
        Tuple of (optimized_bytes, new_mime_type, new_extension).
        If ffmpeg is unavailable or optimization fails, returns original.
    """
    if not _ffmpeg_available():
        logger.info("ffmpeg not available — storing video as-is")
        ext = _ext_for_video_mime(mime_type)
        return data, mime_type, ext

    original_size = len(data)
    timeout_secs = 600  # default, overridden for full re-encode
    tmpdir = tempfile.mkdtemp(prefix="media_opt_")

    try:
        in_ext = _ext_for_video_mime(mime_type)
        in_path = Path(tmpdir) / f"input{in_ext}"
        out_path = Path(tmpdir) / "output.mp4"

        in_path.write_bytes(data)

        # ── Probe first ──
        probe = _probe_media(in_path)
        if probe:
            needs_reencode, reason = _needs_video_reencode(probe, original_size, max_height)
            if not needs_reencode:
                # Already optimal — check if container needs fixing
                if mime_type == "video/mp4":
                    logger.info(
                        f"Video already optimal ({reason}), keeping as-is "
                        f"({original_size:,} bytes)"
                    )
                    return data, mime_type, in_ext
                else:
                    # Fast remux to MP4 container (stream copy, no re-encode)
                    logger.info(
                        f"Video codecs optimal ({reason}), remuxing to MP4 container"
                    )
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", str(in_path),
                        "-c", "copy",
                        "-movflags", "+faststart",
                        str(out_path),
                    ]
                    proc = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=120,
                    )
                    if proc.returncode == 0 and out_path.exists():
                        remuxed = out_path.read_bytes()
                        logger.info(
                            f"Remuxed: {original_size:,} → {len(remuxed):,} bytes"
                        )
                        return remuxed, "video/mp4", ".mp4"
                    # Remux failed — return original
                    return data, mime_type, in_ext
            else:
                logger.info(f"Video needs re-encoding: {reason}")
        else:
            logger.info("Could not probe video — attempting full re-encode")

        # ── Full re-encode needed ──
        scale_filter = _build_scale_filter(in_path, max_height)

        # Adaptive timeout using video duration (much more accurate than file size)
        # Encoding on typical hardware runs at 1-3x realtime for medium preset.
        # We use 1.5x realtime as the estimate, with generous padding.
        size_mb = original_size / (1024 * 1024)
        duration_sec = 0
        if probe:
            try:
                duration_sec = float(probe.get("format", {}).get("duration", 0))
            except (ValueError, TypeError):
                duration_sec = 0

        if duration_sec > 0:
            # Duration-based: assume ~1.5x realtime encoding speed
            # (i.e., a 60-minute video takes ~40 minutes to encode)
            timeout_secs = max(
                900,   # min 15 minutes
                min(14400, int(duration_sec * 1.5)),  # max 4 hours
            )
            logger.info(
                f"Video encode timeout: {timeout_secs}s "
                f"(duration={duration_sec:.0f}s, size={size_mb:.0f} MB)"
            )
        else:
            # Fallback: file-size-based estimate (less accurate)
            timeout_secs = max(
                900,   # min 15 minutes
                min(14400, int(size_mb / 50 * 180)),  # ~3 min per 50 MB
            )
            logger.info(
                f"Video encode timeout: {timeout_secs}s "
                f"(no duration probe, size={size_mb:.0f} MB)"
            )
        # ── Build encoding command ──
        # Prefer GPU (NVENC) if available — 10-30x faster than CPU
        hw_encoder = _detect_hw_encoder()

        cmd = ["ffmpeg", "-y", "-i", str(in_path)]

        if hw_encoder == "h264_nvenc":
            # NVIDIA NVENC: hardware encoding on GPU
            # Preset names: slow/medium/fast (old SDK), p1-p7 (new SDK)
            # Use 'medium' which works on all SDK versions (= hq 1 pass)
            # Rate control: vbr_hq for quality-focused variable bitrate
            cmd.extend([
                "-c:v", "h264_nvenc",
                "-preset", "medium",
                "-rc", "vbr_hq",
                "-qmin", str(crf - 2),   # quality range floor
                "-qmax", str(crf + 4),   # quality range ceiling
                "-b:v", video_bitrate,   # target bitrate
                "-maxrate", video_bitrate,
                "-bufsize", "3M",
                "-profile:v", "high",
                "-pix_fmt", "yuv420p",
                "-gpu", "0",             # use first GPU (RTX 2080, not GT 1030)
            ])
            encoder_label = "NVENC (GPU)"
            # NVENC is much faster — reduce timeout (typically 10-30x realtime)
            if duration_sec > 0:
                timeout_secs = max(300, min(3600, int(duration_sec * 0.3)))
            else:
                timeout_secs = max(300, min(3600, int(size_mb / 100 * 30)))
        else:
            # CPU: libx264 with 'fast' preset (good balance of speed + quality)
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "fast",
                "-threads", "0",      # use all CPU cores
                "-crf", str(crf),
                "-maxrate", video_bitrate,
                "-bufsize", "3M",
                "-profile:v", "high",
                "-pix_fmt", "yuv420p",
            ])
            encoder_label = "libx264 (CPU)"

        # Audio + container settings (same for both)
        cmd.extend([
            "-c:a", "aac",
            "-b:a", audio_bitrate,
            "-movflags", "+faststart",
        ])

        if scale_filter:
            cmd.extend(["-vf", scale_filter])

        cmd.append(str(out_path))

        logger.info(
            f"Starting video re-encode: {encoder_label}, "
            f"{original_size/1024/1024:.0f} MB, timeout={timeout_secs}s"
        )

        # Initialize optimization state for frontend polling
        import time as _time
        global _active_ffmpeg_proc, _optimization_state

        _optimization_state = {
            "status": "encoding",
            "encoder": encoder_label,
            "deadline": timeout_secs,
            "deadline_warning": False,
            "elapsed": 0,
            "fps": "",
            "speed": "",
            "time": "00:00:00",
            "size_mb": size_mb,
            "duration_sec": duration_sec,
        }

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _active_ffmpeg_proc = proc  # store for cancellation

        stderr_lines = []
        start_time = _time.monotonic()
        last_log_time = start_time
        last_state_update = start_time
        grace_deadline = None  # set when soft deadline is hit

        try:
            while True:
                # Check if process has finished
                retcode = proc.poll()

                # Read available stderr (ffmpeg writes progress to stderr)
                line = proc.stderr.readline()
                if line:
                    stderr_lines.append(line.rstrip())
                    now = _time.monotonic()
                    elapsed = now - start_time

                    # Parse ffmpeg progress and update state for frontend
                    progress = _parse_ffmpeg_progress(line)
                    if progress and (now - last_state_update >= 2.0):
                        _optimization_state.update({
                            "elapsed": round(elapsed, 1),
                            "fps": progress.get("fps", _optimization_state.get("fps", "")),
                            "speed": progress.get("speed", _optimization_state.get("speed", "")),
                            "time": progress.get("time", _optimization_state.get("time", "")),
                        })
                        last_state_update = now

                    # Log progress periodically
                    if now - last_log_time >= 5.0:
                        progress_line = line.strip()
                        logger.info(
                            f"ffmpeg [{elapsed:.0f}s]: {progress_line[:120]}"
                        )
                        last_log_time = now

                if retcode is not None:
                    # Process finished — read remaining stderr
                    remaining = proc.stderr.read()
                    if remaining:
                        stderr_lines.extend(remaining.rstrip().split('\n'))
                    break

                # ── Soft deadline with grace period ──
                elapsed = _time.monotonic() - start_time
                current_deadline = _optimization_state.get("deadline", timeout_secs)

                if elapsed > current_deadline:
                    if not _optimization_state.get("deadline_warning"):
                        # First time hitting deadline — start grace period
                        _optimization_state["deadline_warning"] = True
                        grace_deadline = _time.monotonic() + 60  # 60s grace
                        logger.warning(
                            f"Optimization deadline reached ({current_deadline:.0f}s). "
                            f"Grace period: 60s. User can extend."
                        )

                    elif grace_deadline and _time.monotonic() > grace_deadline:
                        # Grace period expired without extension — kill
                        logger.warning(
                            f"Grace period expired — killing ffmpeg "
                            f"(elapsed={elapsed:.0f}s, deadline={current_deadline:.0f}s)"
                        )
                        proc.kill()
                        proc.wait()
                        raise subprocess.TimeoutExpired(cmd, current_deadline)

                    # If deadline_warning is True but deadline was extended
                    # (extend_optimization sets deadline_warning back to False),
                    # we reset grace_deadline
                    if not _optimization_state.get("deadline_warning"):
                        grace_deadline = None

        except subprocess.TimeoutExpired:
            raise  # re-raise for the outer handler

        _active_ffmpeg_proc = None  # clear reference
        _optimization_state = {"status": "idle"}
        stderr_text = '\n'.join(stderr_lines)
        elapsed_total = _time.monotonic() - start_time
        logger.info(f"ffmpeg finished in {elapsed_total:.0f}s (rc={proc.returncode})")

        if proc.returncode != 0:
            if proc.returncode == -9:
                logger.info("ffmpeg killed (cancelled by user)")
            else:
                logger.warning(
                    f"ffmpeg video optimization failed (rc={proc.returncode}): "
                    f"{stderr_text[-500:]}"
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
        logger.warning(
            f"ffmpeg video optimization timed out ({timeout_secs}s) "
            f"for {original_size/1024/1024:.0f} MB file"
        )
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


# ── Text / document compression ──────────────────────────────


def _is_compressible(mime_type: str, original_name: str = "") -> bool:
    """Check if a file is text/document that benefits from gzip."""
    if mime_type in COMPRESSIBLE_MIMES:
        return True
    if mime_type.startswith("text/"):
        return True
    ext = Path(original_name).suffix.lower() if original_name else ""
    return ext in COMPRESSIBLE_EXTENSIONS


def optimize_text(
    data: bytes,
    mime_type: str,
    original_name: str = "",
) -> Tuple[bytes, str, str, bool]:
    """
    Gzip compress text/document files.

    Stored as gzip on disk. The serving layer decompresses
    on demand (or sends with Content-Encoding: gzip).

    Returns:
        Tuple of (compressed_bytes, original_mime, ".gz", was_compressed).
    """
    original_size = len(data)

    if original_size < TEXT_COMPRESS_THRESHOLD:
        import mimetypes as mt
        ext = mt.guess_extension(mime_type) or ".bin"
        return data, mime_type, ext, False

    compressed = gzip.compress(data, compresslevel=9)

    if len(compressed) >= original_size:
        import mimetypes as mt
        ext = mt.guess_extension(mime_type) or ".bin"
        logger.info(
            f"Text compression did not help ({original_size:,} → "
            f"{len(compressed):,} bytes), keeping original"
        )
        return data, mime_type, ext, False

    pct = len(compressed) / original_size * 100
    # Keep original extension + .gz so we know how to decompress + serve
    import mimetypes as mt
    base_ext = mt.guess_extension(mime_type) or ".bin"
    gz_ext = base_ext + ".gz"

    logger.info(
        f"Text compressed: {original_size:,} → {len(compressed):,} bytes "
        f"({pct:.0f}%) [{mime_type}]"
    )

    # Store as application/gzip but preserve original mime in manifest
    return compressed, mime_type, gz_ext, True


def decompress_if_gzipped(data: bytes) -> bytes:
    """
    Decompress gzip data if it has the gzip magic bytes.
    Used by the serving layer to transparently decompress stored files.
    """
    if len(data) >= 2 and data[:2] == b'\x1f\x8b':
        try:
            return gzip.decompress(data)
        except Exception:
            pass
    return data


# ── PDF optimization ─────────────────────────────────────────


def optimize_pdf(
    data: bytes,
    mime_type: str,
) -> Tuple[bytes, str, str, bool]:
    """
    Optimize PDF using Ghostscript (if available).

    Uses /ebook quality preset which preserves readability
    while reducing scanned/image-heavy PDFs significantly.

    Returns:
        Tuple of (optimized_bytes, mime_type, ".pdf", was_optimized).
    """
    if not shutil.which("gs"):
        logger.debug("ghostscript (gs) not available — storing PDF as-is")
        return data, mime_type, ".pdf", False

    original_size = len(data)
    if original_size < 100 * 1024:  # Skip tiny PDFs
        return data, mime_type, ".pdf", False

    tmpdir = tempfile.mkdtemp(prefix="pdf_opt_")
    try:
        in_path = Path(tmpdir) / "input.pdf"
        out_path = Path(tmpdir) / "output.pdf"
        in_path.write_bytes(data)

        cmd = [
            "gs", "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            "-dPDFSETTINGS=/ebook",
            "-dNOPAUSE", "-dBATCH", "-dQUIET",
            f"-sOutputFile={out_path}",
            str(in_path),
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if proc.returncode != 0 or not out_path.exists():
            logger.debug(f"Ghostscript failed (rc={proc.returncode})")
            return data, mime_type, ".pdf", False

        optimized = out_path.read_bytes()

        if len(optimized) >= original_size:
            logger.info(
                f"PDF optimization did not reduce size "
                f"({original_size:,} → {len(optimized):,}), keeping original"
            )
            return data, mime_type, ".pdf", False

        pct = len(optimized) / original_size * 100
        logger.info(
            f"PDF optimized: {original_size:,} → {len(optimized):,} bytes "
            f"({pct:.0f}%)"
        )
        return optimized, mime_type, ".pdf", True

    except subprocess.TimeoutExpired:
        logger.warning("Ghostscript PDF optimization timed out (120s)")
        return data, mime_type, ".pdf", False
    except Exception as e:
        logger.warning(f"PDF optimization error: {e}")
        return data, mime_type, ".pdf", False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Universal dispatcher ─────────────────────────────────────


def optimize_media(
    data: bytes,
    mime_type: str,
    original_name: str = "",
) -> Tuple[bytes, str, str, bool]:
    """
    Universal optimization dispatcher — picks the best optimizer for any MIME type.

    Nothing escapes without a compression attempt if it's large enough.

    Returns:
        Tuple of (optimized_bytes, new_mime_type, new_extension, was_optimized).
    """
    try:
        # ── Images ──
        if should_optimize_image(len(data), mime_type):
            opt_data, opt_mime, opt_ext = optimize_image(data, mime_type)
            was_optimized = len(opt_data) < len(data)
            return opt_data, opt_mime, opt_ext, was_optimized

        # ── Video ──
        if mime_type.startswith("video/"):
            opt_data, opt_mime, opt_ext = optimize_video(data, mime_type)
            was_optimized = len(opt_data) < len(data)
            return opt_data, opt_mime, opt_ext, was_optimized

        # ── Audio ──
        if mime_type.startswith("audio/"):
            opt_data, opt_mime, opt_ext = optimize_audio(data, mime_type)
            was_optimized = len(opt_data) < len(data)
            return opt_data, opt_mime, opt_ext, was_optimized

        # ── PDF ──
        if mime_type == "application/pdf":
            return optimize_pdf(data, mime_type)

        # ── Text / document (gzip) ──
        if _is_compressible(mime_type, original_name):
            return optimize_text(data, mime_type, original_name)

        # ── Fallback: try gzip for anything unknown but large ──
        # Archives (zip, tar, 7z, gz) are already compressed — skip
        skip_mimes = {
            "application/zip", "application/gzip", "application/x-tar",
            "application/x-7z-compressed", "application/x-bzip2",
            "application/x-xz", "application/x-rar-compressed",
        }
        if mime_type not in skip_mimes and len(data) > TEXT_COMPRESS_THRESHOLD:
            compressed = gzip.compress(data, compresslevel=6)
            if len(compressed) < len(data) * 0.9:  # only keep if >10% savings
                import mimetypes as mt
                base_ext = mt.guess_extension(mime_type) or ".bin"
                logger.info(
                    f"Generic gzip: {len(data):,} → {len(compressed):,} bytes "
                    f"({len(compressed)/len(data)*100:.0f}%) [{mime_type}]"
                )
                return compressed, mime_type, base_ext + ".gz", True

        # No optimization available/worthwhile
        import mimetypes as mt
        ext = mt.guess_extension(mime_type) or ".bin"
        return data, mime_type, ext, False

    except Exception as e:
        # Defense in depth — never let an optimizer crash take down the upload
        logger.error(
            f"Optimization failed unexpectedly for {original_name} "
            f"({mime_type}, {len(data):,} bytes): {e}",
            exc_info=True,
        )
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
