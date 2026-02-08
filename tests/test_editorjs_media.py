"""
Tests for media:// URI resolution in EditorJSRenderer and new block types.

Covers:
- media:// URI resolution with resolver callback
- Restricted media placeholder rendering
- External URL passthrough (no resolver needed)
- Image block with media:// + Editor.js options (stretched, border, bg)
- Attachment block rendering with file size formatting
- Video block rendering with poster image
- Audio block rendering
- No-resolver fallback behavior
"""

from __future__ import annotations

import pytest

from src.site.editorjs import EditorJSRenderer, MEDIA_URI_PREFIX


# -- Fixtures -----------------------------------------------------------------


def _resolver_with_map(media_map: dict):
    """Create a resolver callback from a {media_id: url} dict."""
    def resolver(media_id: str):
        return media_map.get(media_id)
    return resolver


VISIBLE_MAP = {
    "img_001": "/media/evidence-photo.jpg",
    "doc_001": "/media/contract.pdf",
    "vid_001": "/media/deposition.mp4",
    "aud_001": "/media/recording.mp3",
    "img_002": "/media/poster.jpg",
}


# -- Image block ---------------------------------------------------------------


class TestImageBlock:
    """Verify image rendering with media:// resolution."""

    def test_external_url_passthrough(self):
        """External URLs should render directly without resolver."""
        renderer = EditorJSRenderer()
        content = {"blocks": [{"type": "image", "data": {
            "url": "https://example.com/photo.jpg", "caption": "External"
        }}]}
        html = renderer.render(content)
        assert 'src="https://example.com/photo.jpg"' in html
        assert '<figcaption>' in html

    def test_media_uri_resolved(self):
        """media:// URI should be resolved to real path."""
        resolver = _resolver_with_map(VISIBLE_MAP)
        renderer = EditorJSRenderer(media_resolver=resolver)
        content = {"blocks": [{"type": "image", "data": {
            "url": "media://img_001", "caption": "Evidence"
        }}]}
        html = renderer.render(content)
        assert 'src="/media/evidence-photo.jpg"' in html
        assert "Evidence" in html

    def test_media_uri_restricted(self):
        """media:// URI for restricted media should show placeholder."""
        resolver = _resolver_with_map({})  # Nothing visible
        renderer = EditorJSRenderer(media_resolver=resolver)
        content = {"blocks": [{"type": "image", "data": {
            "url": "media://img_secret", "caption": "Secret"
        }}]}
        html = renderer.render(content)
        assert "media-restricted" in html
        assert "🔒" in html
        assert "img_secret" in html
        assert "image" in html  # media type

    def test_media_uri_no_resolver(self):
        """Without resolver, media:// URI should pass through raw."""
        renderer = EditorJSRenderer()  # No resolver
        content = {"blocks": [{"type": "image", "data": {
            "url": "media://img_001", "caption": "Test"
        }}]}
        html = renderer.render(content)
        assert 'src="media://img_001"' in html  # Raw URI preserved

    def test_image_stretched(self):
        """Stretched images should get the stretched class."""
        renderer = EditorJSRenderer()
        content = {"blocks": [{"type": "image", "data": {
            "url": "https://example.com/photo.jpg", "stretched": True
        }}]}
        html = renderer.render(content)
        assert "image-stretched" in html

    def test_image_with_border(self):
        """Bordered images should get the bordered class."""
        renderer = EditorJSRenderer()
        content = {"blocks": [{"type": "image", "data": {
            "url": "https://example.com/photo.jpg", "withBorder": True
        }}]}
        html = renderer.render(content)
        assert "image-bordered" in html

    def test_image_with_background(self):
        """Background images should get the bg class."""
        renderer = EditorJSRenderer()
        content = {"blocks": [{"type": "image", "data": {
            "url": "https://example.com/photo.jpg", "withBackground": True
        }}]}
        html = renderer.render(content)
        assert "image-bg" in html

    def test_image_all_options(self):
        """All image options should be combined."""
        renderer = EditorJSRenderer()
        content = {"blocks": [{"type": "image", "data": {
            "url": "https://example.com/photo.jpg",
            "stretched": True, "withBorder": True, "withBackground": True
        }}]}
        html = renderer.render(content)
        assert "image-stretched" in html
        assert "image-bordered" in html
        assert "image-bg" in html


# -- Attachment block ----------------------------------------------------------


class TestAttachmentBlock:
    """Verify attachment rendering."""

    def test_attachment_basic(self):
        """Basic attachment should render download link."""
        resolver = _resolver_with_map(VISIBLE_MAP)
        renderer = EditorJSRenderer(media_resolver=resolver)
        content = {"blocks": [{"type": "attachment", "data": {
            "url": "media://doc_001", "title": "Contract v2", "size": 845322
        }}]}
        html = renderer.render(content)
        assert 'href="/media/contract.pdf"' in html
        assert "Contract v2" in html
        assert "download" in html
        assert "📎" in html

    def test_attachment_with_file_size(self):
        """Attachment should show formatted file size."""
        resolver = _resolver_with_map(VISIBLE_MAP)
        renderer = EditorJSRenderer(media_resolver=resolver)
        content = {"blocks": [{"type": "attachment", "data": {
            "url": "media://doc_001", "title": "Big file", "size": 2048000
        }}]}
        html = renderer.render(content)
        assert "2.0 MB" in html or "1.9 MB" in html  # ~2MB

    def test_attachment_restricted(self):
        """Restricted attachment should show placeholder."""
        resolver = _resolver_with_map({})
        renderer = EditorJSRenderer(media_resolver=resolver)
        content = {"blocks": [{"type": "attachment", "data": {
            "url": "media://doc_secret"
        }}]}
        html = renderer.render(content)
        assert "media-restricted" in html
        assert "document" in html

    def test_attachment_external_url(self):
        """External attachment URL should work without resolver."""
        renderer = EditorJSRenderer()
        content = {"blocks": [{"type": "attachment", "data": {
            "url": "https://example.com/doc.pdf", "title": "External doc"
        }}]}
        html = renderer.render(content)
        assert 'href="https://example.com/doc.pdf"' in html

    def test_attachment_editor_format(self):
        """Editor.js attaches tool uses file.url / file.name format."""
        renderer = EditorJSRenderer()
        content = {"blocks": [{"type": "attachment", "data": {
            "file": {"url": "https://example.com/f.pdf", "name": "Report", "size": 1024}
        }}]}
        html = renderer.render(content)
        assert "Report" in html
        assert 'href="https://example.com/f.pdf"' in html


# -- Video block ---------------------------------------------------------------


class TestVideoBlock:
    """Verify video rendering."""

    def test_video_basic(self):
        """Basic video should render HTML5 video player."""
        resolver = _resolver_with_map(VISIBLE_MAP)
        renderer = EditorJSRenderer(media_resolver=resolver)
        content = {"blocks": [{"type": "video", "data": {
            "url": "media://vid_001", "caption": "Deposition"
        }}]}
        html = renderer.render(content)
        assert "<video" in html
        assert "controls" in html
        assert 'src="/media/deposition.mp4"' in html
        assert "Deposition" in html

    def test_video_with_poster(self):
        """Video with poster image should include poster attribute."""
        resolver = _resolver_with_map(VISIBLE_MAP)
        renderer = EditorJSRenderer(media_resolver=resolver)
        content = {"blocks": [{"type": "video", "data": {
            "url": "media://vid_001", "poster": "media://img_002"
        }}]}
        html = renderer.render(content)
        assert 'poster="/media/poster.jpg"' in html

    def test_video_restricted(self):
        """Restricted video should show placeholder."""
        resolver = _resolver_with_map({})
        renderer = EditorJSRenderer(media_resolver=resolver)
        content = {"blocks": [{"type": "video", "data": {
            "url": "media://vid_secret"
        }}]}
        html = renderer.render(content)
        assert "media-restricted" in html
        assert "video" in html


# -- Audio block ---------------------------------------------------------------


class TestAudioBlock:
    """Verify audio rendering."""

    def test_audio_basic(self):
        """Basic audio should render HTML5 audio player."""
        resolver = _resolver_with_map(VISIBLE_MAP)
        renderer = EditorJSRenderer(media_resolver=resolver)
        content = {"blocks": [{"type": "audio", "data": {
            "url": "media://aud_001", "caption": "Phone recording"
        }}]}
        html = renderer.render(content)
        assert "<audio" in html
        assert "controls" in html
        assert 'src="/media/recording.mp3"' in html
        assert "Phone recording" in html

    def test_audio_restricted(self):
        """Restricted audio should show placeholder."""
        resolver = _resolver_with_map({})
        renderer = EditorJSRenderer(media_resolver=resolver)
        content = {"blocks": [{"type": "audio", "data": {
            "url": "media://aud_secret"
        }}]}
        html = renderer.render(content)
        assert "media-restricted" in html
        assert "audio" in html


# -- Media placeholder ---------------------------------------------------------


class TestMediaPlaceholder:
    """Verify restricted media placeholder HTML."""

    def test_placeholder_structure(self):
        """Placeholder should contain media ID and lock icon."""
        resolver = _resolver_with_map({})
        renderer = EditorJSRenderer(media_resolver=resolver)
        content = {"blocks": [{"type": "image", "data": {
            "url": "media://secret_img"
        }}]}
        html = renderer.render(content)
        assert 'data-media-id="secret_img"' in html
        assert 'data-media-type="image"' in html
        assert "🔒" in html
        assert "restricted" in html

    def test_placeholder_for_each_type(self):
        """Each media type should show its specific type name."""
        resolver = _resolver_with_map({})
        renderer = EditorJSRenderer(media_resolver=resolver)

        for block_type, expected_type in [
            ("image", "image"),
            ("attachment", "document"),
            ("video", "video"),
            ("audio", "audio"),
        ]:
            content = {"blocks": [{"type": block_type, "data": {
                "url": "media://restricted_id"
            }}]}
            html = renderer.render(content)
            assert expected_type in html, f"Expected '{expected_type}' in {block_type} placeholder"


# -- File size formatting ------------------------------------------------------


class TestFileSizeFormatting:
    """Verify file size formatting helper."""

    def test_bytes(self):
        assert EditorJSRenderer._format_file_size(512) == "512 B"

    def test_kilobytes(self):
        assert EditorJSRenderer._format_file_size(10240) == "10.0 KB"

    def test_megabytes(self):
        result = EditorJSRenderer._format_file_size(5 * 1024 * 1024)
        assert result == "5.0 MB"

    def test_gigabytes(self):
        result = EditorJSRenderer._format_file_size(2 * 1024 * 1024 * 1024)
        assert result == "2.0 GB"


# -- Backward compatibility ----------------------------------------------------


class TestBackwardCompatibility:
    """Ensure existing block types still work after changes."""

    def test_paragraph_still_works(self):
        """Paragraph rendering should be unchanged."""
        renderer = EditorJSRenderer()
        content = {"blocks": [{"type": "paragraph", "data": {"text": "Hello world"}}]}
        assert "<p>Hello world</p>" in renderer.render(content)

    def test_header_still_works(self):
        """Header rendering should be unchanged."""
        renderer = EditorJSRenderer()
        content = {"blocks": [{"type": "header", "data": {"text": "Title", "level": 2}}]}
        assert "<h2>Title</h2>" in renderer.render(content)

    def test_image_without_resolver_still_works(self):
        """Image with plain URL should render without resolver."""
        renderer = EditorJSRenderer()
        content = {"blocks": [{"type": "image", "data": {
            "url": "/static/logo.png", "caption": "Logo"
        }}]}
        html = renderer.render(content)
        assert 'src="/static/logo.png"' in html
        assert "Logo" in html

    def test_unknown_block_type(self):
        """Unknown block types should render comment."""
        renderer = EditorJSRenderer()
        content = {"blocks": [{"type": "nonexistent", "data": {}}]}
        html = renderer.render(content)
        assert "Unknown block type" in html
