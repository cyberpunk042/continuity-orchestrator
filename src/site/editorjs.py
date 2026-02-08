"""
Editor.js Content Pipeline — Parse and render Editor.js JSON to HTML.

This module provides:
1. Content storage location: `content/articles/*.json`
2. Parser: Editor.js JSON → semantic HTML
3. Media resolution via `media://` URI scheme
4. Integration with site generator

## Content Structure

content/
├── articles/
│   ├── full_disclosure.json    # Editor.js JSON for full release
│   ├── partial_notice.json     # Editor.js JSON for partial
│   └── about.json              # Static about page
└── media/
    ├── manifest.json           # Media registry
    └── img_001.enc             # Encrypted media files

## Editor.js JSON Format

{
    "time": 1706123456789,
    "version": "2.28.0",
    "blocks": [
        {"type": "header", "data": {"text": "Title", "level": 1}},
        {"type": "paragraph", "data": {"text": "Content here..."}},
        {"type": "image", "data": {"url": "media://img_001", "caption": "Evidence"}},
        {"type": "attachment", "data": {"url": "media://doc_001", "title": "Contract"}},
        {"type": "video", "data": {"url": "media://vid_001", "caption": "Deposition"}}
    ]
}

## Media Resolution

Blocks with `url` starting with `media://` are resolved at render time:
- **Visible**: `media://img_001` → `/media/evidence-photo.jpg`
- **Restricted**: `media://img_001` → lockbox placeholder HTML
- **Preview**: `media://img_001` → `/api/content/media/img_001/preview`

Resolution is handled by the `media_resolver` callback:
    resolver(media_id: str) → Optional[str]  # returns URL or None

## Usage

    from src.site.editorjs import EditorJSRenderer

    renderer = EditorJSRenderer()
    html = renderer.render(json_content)

    # With media resolution:
    resolver = lambda mid: f"/media/{mid}.jpg" if visible else None
    renderer = EditorJSRenderer(media_resolver=resolver)
    html = renderer.render(json_content)
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Prefix for media:// URI references in Editor.js blocks
MEDIA_URI_PREFIX = "media://"


class EditorJSRenderer:
    """
    Render Editor.js JSON blocks to semantic HTML.
    
    Supports core block types:
    - paragraph
    - header (h1-h6)
    - list (ordered, unordered, checklist)
    - quote
    - code
    - delimiter
    - warning
    - table
    - image (with media:// resolution)
    - attachment (PDF, document downloads)
    - video (embedded video player)
    - audio (embedded audio player)
    """
    
    def __init__(
        self,
        sanitize: bool = True,
        media_resolver: Optional[Callable[[str], Optional[str]]] = None,
    ):
        """
        Initialize renderer.
        
        Args:
            sanitize: Whether to escape HTML in text content (default True)
            media_resolver: Optional callback to resolve media:// URIs.
                Takes a media ID string, returns a URL string if the media
                is accessible, or None if restricted/unavailable.
        """
        self.sanitize = sanitize
        self.media_resolver = media_resolver
        
        # Block type → render method
        self.renderers = {
            "paragraph": self._render_paragraph,
            "header": self._render_header,
            "list": self._render_list,
            "quote": self._render_quote,
            "code": self._render_code,
            "delimiter": self._render_delimiter,
            "warning": self._render_warning,
            "table": self._render_table,
            "image": self._render_image,
            "attachment": self._render_attachment,
            "video": self._render_video,
            "audio": self._render_audio,
            "raw": self._render_raw,
            "checklist": self._render_checklist,
        }
    
    def render(self, content: Dict[str, Any]) -> str:
        """
        Render Editor.js content to HTML.
        
        Args:
            content: Editor.js JSON object with "blocks" array
        
        Returns:
            Rendered HTML string
        """
        blocks = content.get("blocks", [])
        html_parts = []
        
        for block in blocks:
            block_type = block.get("type", "paragraph")
            block_data = block.get("data", {})
            
            renderer = self.renderers.get(block_type, self._render_unknown)
            rendered = renderer(block_data)
            
            if rendered:
                html_parts.append(rendered)
        
        return "\n".join(html_parts)
    
    def render_file(self, path: Path) -> str:
        """Load and render an Editor.js JSON file."""
        content = json.loads(path.read_text())
        return self.render(content)
    
    def _escape(self, text: str) -> str:
        """Escape HTML if sanitization is enabled."""
        if self.sanitize:
            return html.escape(text)
        return text
    
    def _parse_inline(self, text: str) -> str:
        """
        Parse inline formatting from Editor.js.
        
        Editor.js uses simple tags: <b>, <i>, <a>, <code>
        We allow these through but escape other content.
        """
        if not self.sanitize:
            return text
        
        # Temporarily replace allowed tags
        allowed_pattern = r'(</?(?:b|i|a|code|mark|u|s)[^>]*>)'
        parts = re.split(allowed_pattern, text)
        
        result = []
        for part in parts:
            if re.match(allowed_pattern, part):
                result.append(part)  # Keep allowed tags
            else:
                result.append(html.escape(part))  # Escape rest
        
        return "".join(result)
    
    def _render_paragraph(self, data: Dict) -> str:
        """Render paragraph block."""
        text = self._parse_inline(data.get("text", ""))
        return f'<p>{text}</p>'
    
    def _render_header(self, data: Dict) -> str:
        """Render header block (h1-h6)."""
        level = min(6, max(1, data.get("level", 2)))
        text = self._parse_inline(data.get("text", ""))
        return f'<h{level}>{text}</h{level}>'
    
    def _render_list(self, data: Dict) -> str:
        """Render list block (ordered or unordered)."""
        style = data.get("style", "unordered")
        items = data.get("items", [])
        
        tag = "ol" if style == "ordered" else "ul"
        
        list_items = []
        for item in items:
            # Handle nested items (Editor.js 2.x format)
            if isinstance(item, dict):
                content = self._parse_inline(item.get("content", ""))
                nested = item.get("items", [])
                if nested:
                    nested_html = self._render_list({"style": style, "items": nested})
                    list_items.append(f'<li>{content}{nested_html}</li>')
                else:
                    list_items.append(f'<li>{content}</li>')
            else:
                # Simple string item
                list_items.append(f'<li>{self._parse_inline(item)}</li>')
        
        return f'<{tag}>\n{"".join(list_items)}\n</{tag}>'
    
    def _render_checklist(self, data: Dict) -> str:
        """Render checklist block."""
        items = data.get("items", [])
        
        list_items = []
        for item in items:
            text = self._parse_inline(item.get("text", ""))
            checked = item.get("checked", False)
            checkbox = "☑" if checked else "☐"
            list_items.append(f'<li class="checklist-item">{checkbox} {text}</li>')
        
        return f'<ul class="checklist">\n{"".join(list_items)}\n</ul>'
    
    def _render_quote(self, data: Dict) -> str:
        """Render quote block."""
        text = self._parse_inline(data.get("text", ""))
        caption = data.get("caption", "")
        
        if caption:
            caption_html = f'\n<cite>{self._parse_inline(caption)}</cite>'
        else:
            caption_html = ""
        
        return f'<blockquote>\n<p>{text}</p>{caption_html}\n</blockquote>'
    
    def _render_code(self, data: Dict) -> str:
        """Render code block."""
        code = self._escape(data.get("code", ""))
        language = data.get("language", "")
        
        lang_class = f' class="language-{language}"' if language else ""
        return f'<pre><code{lang_class}>{code}</code></pre>'
    
    def _render_delimiter(self, data: Dict) -> str:
        """Render horizontal rule / delimiter."""
        return '<hr class="delimiter">'
    
    def _render_warning(self, data: Dict) -> str:
        """Render warning/alert block."""
        title = self._parse_inline(data.get("title", ""))
        message = self._parse_inline(data.get("message", ""))
        
        return f'''<div class="warning">
<strong>{title}</strong>
<p>{message}</p>
</div>'''
    
    def _render_table(self, data: Dict) -> str:
        """Render table block."""
        content = data.get("content", [])
        with_headings = data.get("withHeadings", False)
        
        if not content:
            return ""
        
        rows = []
        for i, row in enumerate(content):
            cells = []
            for cell in row:
                tag = "th" if (i == 0 and with_headings) else "td"
                cells.append(f'<{tag}>{self._parse_inline(cell)}</{tag}>')
            rows.append(f'<tr>{"".join(cells)}</tr>')
        
        return f'<table>\n{"".join(rows)}\n</table>'
    
    def _resolve_media_url(self, url: str) -> Optional[str]:
        """
        Resolve a media:// URI to a real URL.
        
        Returns the resolved URL, or None if the media is restricted.
        Non-media:// URLs are returned as-is.
        """
        if not url.startswith(MEDIA_URI_PREFIX):
            return url  # Regular URL, pass through
        
        media_id = url[len(MEDIA_URI_PREFIX):]
        
        if self.media_resolver:
            return self.media_resolver(media_id)
        
        # No resolver — return the raw URI (admin preview may handle it)
        return url
    
    def _render_media_placeholder(self, media_id: str, media_type: str = "media") -> str:
        """
        Render a locked/restricted media placeholder.
        
        Shown when a media:// URI cannot be resolved (stage restriction).
        """
        return (
            f'<div class="media-restricted" data-media-id="{self._escape(media_id)}" '
            f'data-media-type="{self._escape(media_type)}">'
            f'<span class="media-restricted-icon">🔒</span>'
            f'<span class="media-restricted-text">'
            f'This {media_type} is restricted at the current disclosure stage.'
            f'</span></div>'
        )
    
    def _render_image(self, data: Dict) -> str:
        """Render image block with media:// resolution support.
        
        Handles three URL sources:
        - data.file.url — standard @editorjs/image format
        - data.url — legacy flat format
        - Supports media://, data:, https://, http:// schemes
        """
        # Editor.js image tool stores URL in data.file.url
        file_obj = data.get("file", {})
        raw_url = file_obj.get("url", "") if isinstance(file_obj, dict) else ""
        # Fall back to legacy flat format
        if not raw_url:
            raw_url = data.get("url", "")
        
        caption = data.get("caption", "")
        alt = self._escape(caption or "Image")
        
        # Check for media:// URI
        if raw_url.startswith(MEDIA_URI_PREFIX):
            media_id = raw_url[len(MEDIA_URI_PREFIX):]
            resolved = self._resolve_media_url(raw_url)
            if resolved is None:
                return self._render_media_placeholder(media_id, "image")
            url = self._escape(resolved)
        elif raw_url.startswith("data:"):
            # Base64 data URI — pass through as-is (no escaping needed)
            url = raw_url
        else:
            url = self._escape(raw_url)
        
        # Build classes from Editor.js image options
        classes = []
        if data.get("stretched"):
            classes.append("image-stretched")
        if data.get("withBorder"):
            classes.append("image-bordered")
        if data.get("withBackground"):
            classes.append("image-bg")
        class_attr = f' class="{" ".join(classes)}"' if classes else ""
        
        figure_html = f'<img src="{url}" alt="{alt}" loading="lazy">'
        
        if caption:
            figure_html += f'\n<figcaption>{self._parse_inline(caption)}</figcaption>'
        
        return f'<figure{class_attr}>\n{figure_html}\n</figure>'
    
    def _render_attachment(self, data: Dict) -> str:
        """
        Render attachment block (PDF, document download).
        
        Data format:
            {"url": "media://doc_001", "title": "Contract", "size": 845322}
        """
        raw_url = data.get("url", data.get("file", {}).get("url", ""))
        title = data.get("title", data.get("file", {}).get("name", "Attachment"))
        size = data.get("size", data.get("file", {}).get("size", 0))
        
        # Check for media:// URI
        if raw_url.startswith(MEDIA_URI_PREFIX):
            media_id = raw_url[len(MEDIA_URI_PREFIX):]
            resolved = self._resolve_media_url(raw_url)
            if resolved is None:
                return self._render_media_placeholder(media_id, "document")
            url = self._escape(resolved)
        else:
            url = self._escape(raw_url)
        
        # Format file size
        size_str = self._format_file_size(size) if size else ""
        size_html = f'<span class="attachment-size">{size_str}</span>' if size_str else ""
        
        return (
            f'<div class="attachment">'
            f'<a href="{url}" class="attachment-link" download>'
            f'<span class="attachment-icon">📎</span>'
            f'<span class="attachment-title">{self._parse_inline(title)}</span>'
            f'{size_html}'
            f'</a></div>'
        )
    
    def _render_video(self, data: Dict) -> str:
        """
        Render video block (HTML5 video player).
        
        Data format:
            {"url": "media://vid_001", "caption": "Deposition", "poster": "media://img_002"}
        """
        raw_url = data.get("url", data.get("file", {}).get("url", ""))
        caption = data.get("caption", "")
        poster_url = data.get("poster", "")
        
        # Resolve main video URL
        if raw_url.startswith(MEDIA_URI_PREFIX):
            media_id = raw_url[len(MEDIA_URI_PREFIX):]
            resolved = self._resolve_media_url(raw_url)
            if resolved is None:
                return self._render_media_placeholder(media_id, "video")
            url = self._escape(resolved)
        else:
            url = self._escape(raw_url)
        
        # Resolve poster image URL if present
        poster_attr = ""
        if poster_url:
            poster_resolved = self._resolve_media_url(poster_url)
            if poster_resolved:
                poster_attr = f' poster="{self._escape(poster_resolved)}"'
        
        video_html = f'<video controls preload="metadata"{poster_attr}><source src="{url}"></video>'
        
        if caption:
            video_html += f'\n<figcaption>{self._parse_inline(caption)}</figcaption>'
        
        return f'<figure class="video-block">\n{video_html}\n</figure>'
    
    def _render_audio(self, data: Dict) -> str:
        """
        Render audio block (HTML5 audio player).
        
        Data format:
            {"url": "media://aud_001", "caption": "Phone recording"}
        """
        raw_url = data.get("url", data.get("file", {}).get("url", ""))
        caption = data.get("caption", "")
        
        # Resolve audio URL
        if raw_url.startswith(MEDIA_URI_PREFIX):
            media_id = raw_url[len(MEDIA_URI_PREFIX):]
            resolved = self._resolve_media_url(raw_url)
            if resolved is None:
                return self._render_media_placeholder(media_id, "audio")
            url = self._escape(resolved)
        else:
            url = self._escape(raw_url)
        
        audio_html = f'<audio controls preload="metadata"><source src="{url}"></audio>'
        
        if caption:
            audio_html += f'\n<p class="audio-caption">{self._parse_inline(caption)}</p>'
        
        return f'<div class="audio-block">\n{audio_html}\n</div>'
    
    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        """Format file size in human-readable form."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    
    def _render_raw(self, data: Dict) -> str:
        """Render raw HTML block (use with caution)."""
        if self.sanitize:
            # In sanitized mode, escape raw HTML
            return f'<pre class="raw-html">{self._escape(data.get("html", ""))}</pre>'
        return data.get("html", "")
    
    def _render_unknown(self, data: Dict) -> str:
        """Fallback for unknown block types."""
        return f'<!-- Unknown block type -->'


class ContentManager:
    """
    Manage content articles for the static site.
    
    Articles are stored as Editor.js JSON files in content/articles/
    """
    
    def __init__(self, content_dir: Optional[Path] = None):
        self.content_dir = content_dir or self._default_content_dir()
        self.renderer = EditorJSRenderer()
    
    def _default_content_dir(self) -> Path:
        """Get default content directory."""
        return Path(__file__).parent.parent.parent / "content" / "articles"
    
    def list_articles(self) -> List[Dict[str, Any]]:
        """List all available articles, detecting encrypted ones."""
        if not self.content_dir.exists():
            return []
        
        from ..content.crypto import is_encrypted, get_encryption_key, load_article
        
        articles = []
        for path in sorted(self.content_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text())
                encrypted = is_encrypted(raw)
                
                # Extract title and metadata
                title = path.stem.replace("_", " ").title()
                time_val = None
                version = None
                
                if encrypted:
                    # Try to decrypt for title extraction if key is available
                    key = get_encryption_key()
                    if key:
                        try:
                            content = load_article(path, passphrase=key)
                            time_val = content.get("time")
                            version = content.get("version")
                            for block in content.get("blocks", []):
                                if block.get("type") == "header":
                                    title = block.get("data", {}).get("text", title)
                                    break
                        except Exception:
                            pass  # Use slug-based title
                else:
                    time_val = raw.get("time")
                    version = raw.get("version")
                    for block in raw.get("blocks", []):
                        if block.get("type") == "header":
                            title = block.get("data", {}).get("text", title)
                            break
                
                articles.append({
                    "slug": path.stem,
                    "title": title,
                    "path": path,
                    "time": time_val,
                    "version": version,
                    "encrypted": encrypted,
                })
            except Exception:
                continue
        
        return articles
    
    def get_article(self, slug: str) -> Optional[Dict[str, Any]]:
        """Get a single article by slug, decrypting if needed."""
        path = self.content_dir / f"{slug}.json"
        if not path.exists():
            return None
        
        from ..content.crypto import is_encrypted, load_article
        
        raw = json.loads(path.read_text())
        encrypted = is_encrypted(raw)
        
        # Decrypt if needed (load_article handles this transparently)
        content = load_article(path)
        html = self.renderer.render(content)
        
        # Extract title
        title = slug.replace("_", " ").title()
        for block in content.get("blocks", []):
            if block.get("type") == "header":
                title = block.get("data", {}).get("text", title)
                break
        
        return {
            "slug": slug,
            "title": title,
            "html": html,
            "raw": content,
            "time": content.get("time"),
            "encrypted": encrypted,
        }
    
    def render_article(self, slug: str) -> Optional[str]:
        """Render an article to HTML."""
        article = self.get_article(slug)
        if article:
            return article["html"]
        return None
