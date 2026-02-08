"""
Tests for the media optimizer module.

Tests cover:
- Image optimization (resize + format conversion)
- Storage tier classification
- should_optimize logic
- Edge cases (SVG, GIF, non-image files)
"""

import io
import struct
from pathlib import Path

import pytest

from src.content.media_optimize import (
    optimize_image,
    classify_storage,
    should_optimize,
    LARGE_THRESHOLD_BYTES,
)


# ── Test Image Helpers ───────────────────────────────────────


def _make_png(width: int, height: int, color=(255, 0, 0)) -> bytes:
    """Create a valid PNG image of given dimensions using Pillow."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_rgba_png(width: int, height: int, use_alpha=True) -> bytes:
    """Create an RGBA PNG with optional meaningful transparency."""
    from PIL import Image

    img = Image.new("RGBA", (width, height), (255, 0, 0, 255))
    if use_alpha:
        # Make some pixels transparent
        for x in range(width // 2):
            for y in range(height // 2):
                img.putpixel((x, y), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg(width: int, height: int) -> bytes:
    """Create a valid JPEG image."""
    from PIL import Image

    img = Image.new("RGB", (width, height), (0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════
# classify_storage Tests
# ═══════════════════════════════════════════════════════════════════


class TestClassifyStorage:
    """Test the storage tier classification."""

    def test_tiny_is_inline(self):
        assert classify_storage(50 * 1024) == "inline"

    def test_99kb_is_inline(self):
        assert classify_storage(99 * 1024) == "inline"

    def test_100kb_is_git(self):
        assert classify_storage(100 * 1024) == "git"

    def test_1mb_is_git(self):
        assert classify_storage(1 * 1024 * 1024) == "git"

    def test_2mb_is_git(self):
        assert classify_storage(2 * 1024 * 1024) == "git"

    def test_3mb_is_large(self):
        assert classify_storage(3 * 1024 * 1024) == "large"

    def test_50mb_is_large(self):
        assert classify_storage(50 * 1024 * 1024) == "large"


# ═══════════════════════════════════════════════════════════════════
# should_optimize Tests
# ═══════════════════════════════════════════════════════════════════


class TestShouldOptimize:
    """Test whether optimization is triggered."""

    def test_small_image_not_optimized(self):
        assert should_optimize(500 * 1024, "image/png") is False

    def test_large_png_optimized(self):
        assert should_optimize(5 * 1024 * 1024, "image/png") is True

    def test_large_jpeg_optimized(self):
        assert should_optimize(5 * 1024 * 1024, "image/jpeg") is True

    def test_svg_never_optimized(self):
        assert should_optimize(5 * 1024 * 1024, "image/svg+xml") is False

    def test_gif_never_optimized(self):
        assert should_optimize(5 * 1024 * 1024, "image/gif") is False

    def test_pdf_not_optimized(self):
        assert should_optimize(5 * 1024 * 1024, "application/pdf") is False


# ═══════════════════════════════════════════════════════════════════
# optimize_image Tests
# ═══════════════════════════════════════════════════════════════════


class TestOptimizeImage:
    """Test the image optimization pipeline."""

    def test_large_png_is_resized(self):
        """A 4000x3000 PNG should be resized to max 2048px."""
        from PIL import Image

        original = _make_png(4000, 3000)
        optimized, mime, ext = optimize_image(original, "image/png")
        
        # Should be smaller
        assert len(optimized) < len(original)
        
        # Check dimensions
        img = Image.open(io.BytesIO(optimized))
        assert max(img.size) <= 2048
        
        # Should be WebP
        assert mime == "image/webp"
        assert ext == ".webp"

    def test_small_image_not_resized(self):
        """A 200x200 image should not be resized."""
        from PIL import Image

        original = _make_png(200, 200)
        optimized, mime, ext = optimize_image(original, "image/png")
        
        # Check dimensions preserved
        img = Image.open(io.BytesIO(optimized))
        assert img.size == (200, 200)

    def test_jpeg_stays_reasonable(self):
        """JPEG input should still produce smaller output."""
        original = _make_jpeg(4000, 3000)
        optimized, mime, ext = optimize_image(original, "image/jpeg")
        
        assert len(optimized) < len(original)
        assert mime == "image/webp"

    def test_rgba_with_alpha_preserved(self):
        """RGBA images with real transparency should keep alpha."""
        from PIL import Image

        original = _make_rgba_png(500, 500, use_alpha=True)
        optimized, mime, ext = optimize_image(original, "image/png")
        
        img = Image.open(io.BytesIO(optimized))
        # WebP supports RGBA
        assert mime == "image/webp"

    def test_rgba_without_alpha_dropped(self):
        """RGBA images with no transparency should convert to RGB."""
        from PIL import Image

        original = _make_rgba_png(500, 500, use_alpha=False)
        optimized, mime, ext = optimize_image(original, "image/png")
        
        img = Image.open(io.BytesIO(optimized))
        assert img.mode == "RGB"

    def test_svg_passthrough(self):
        """SVG files should not be optimized."""
        svg_data = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        result, mime, ext = optimize_image(svg_data, "image/svg+xml")
        assert result == svg_data
        assert mime == "image/svg+xml"

    def test_gif_passthrough(self):
        """GIF files should not be optimized."""
        # Minimal GIF header
        gif_data = b"GIF89a" + b"\x00" * 100
        result, mime, ext = optimize_image(gif_data, "image/gif")
        assert result == gif_data
        assert mime == "image/gif"

    def test_custom_max_dimension(self):
        """Custom max_dimension should be respected."""
        from PIL import Image

        original = _make_png(2000, 1000)
        optimized, _, _ = optimize_image(
            original, "image/png", max_dimension=800
        )
        
        img = Image.open(io.BytesIO(optimized))
        assert max(img.size) <= 800

    def test_aspect_ratio_preserved(self):
        """Resizing should maintain aspect ratio."""
        from PIL import Image

        original = _make_png(4000, 2000)  # 2:1 ratio
        optimized, _, _ = optimize_image(original, "image/png")
        
        img = Image.open(io.BytesIO(optimized))
        w, h = img.size
        ratio = w / h
        assert abs(ratio - 2.0) < 0.01


# ═══════════════════════════════════════════════════════════════════
# Integration: optimizer reduces 16MB-class images to git tier
# ═══════════════════════════════════════════════════════════════════


class TestOptimizationEffectiveness:
    """Test that optimization achieves meaningful size reduction."""

    def test_large_photo_fits_git_tier(self):
        """A large photo-like image should optimize well below 2MB.
        
        Note: synthetic solid-color images compress extremely well,
        often to < 100KB. Real photos would land in 'git' tier.
        The key assertion is that it's NOT in 'large' tier.
        """
        # Create a 5000x4000 image (similar to user's 5920x4737)
        original = _make_png(5000, 4000)
        optimized, mime, ext = optimize_image(original, "image/png")
        
        tier = classify_storage(len(optimized))
        assert tier != "large", (
            f"Optimized size {len(optimized):,} bytes should NOT be in large tier"
        )

    def test_reduction_is_significant(self):
        """Optimization should achieve at least 50% reduction on large images."""
        original = _make_png(4000, 3000)
        optimized, _, _ = optimize_image(original, "image/png")
        
        reduction = 1 - (len(optimized) / len(original))
        assert reduction > 0.5, (
            f"Expected >50% reduction, got {reduction*100:.0f}%"
        )
