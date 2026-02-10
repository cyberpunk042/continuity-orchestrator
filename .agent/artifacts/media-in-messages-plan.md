# Media in Messages — Detailed Implementation Plan

## Architecture Overview

Message templates are **markdown** files (`.md`, `.txt`) edited in a plain `<textarea>`.
The existing EditorJS article editor uses structured JSON blocks for media.
Messages need a different approach: **markdown-native media syntax**.

---

## 1. Template-Level Syntax Design

### Standard Markdown Images
```markdown
![caption](media://img_001)
```

### Extended Syntax for Non-Image Media
Markdown has no native video/audio/attachment syntax. We define a simple,
human-readable convention using fenced directives:

```markdown
<!-- For images (standard markdown) -->
![Evidence photo](media://img_001)

<!-- For video -->
{{media:video media://vid_001 caption="Deposition footage"}}

<!-- For audio -->
{{media:audio media://aud_001 caption="Phone recording"}}

<!-- For attachments (any file) -->
{{media:file media://doc_001 title="Contract.pdf"}}
```

**Why this syntax?**
- `![](url)` is standard, universally understood for images
- `{{media:TYPE URI}}` uses the same `${{var}}` delimiter family already in templates
- Easy to parse with a single regex
- Human-readable in the raw markdown
- Won't conflict with Jinja2 (uses `${{}}` not `{{}}` — wait, the template vars
  use `${{}}` already, but `{{media:...}}` starts with `{{media:` which is unique)

**Alternative (simpler):** Use markdown image syntax for ALL types, with a type hint
in the alt text:
```markdown
![caption](media://img_001)           ← image (default)
![video: Deposition](media://vid_001)  ← video (alt starts with "video:")
![audio: Recording](media://aud_001)   ← audio (alt starts with "audio:")
![file: Contract.pdf](media://doc_001) ← attachment (alt starts with "file:")
```

This is simpler — one regex, one pattern. The alt-text prefix determines rendering.
**→ Going with this approach.**

### Final Syntax
```
![caption](media://id)                   → renders as <img>
![video: caption](media://id)            → renders as <video>
![audio: caption](media://id)            → renders as <audio>
![file: filename](media://id)            → renders as download link
![caption](data:image/png;base64,...)    → inline image (small, from paste)
![caption](https://example.com/img.jpg)  → external image
```

---

## 2. Per-Adapter Rendering Matrix

### What each adapter can do with each media type:

| Media Type | Email (HTML) | SMS | X/Twitter | Reddit |
|------------|-------------|-----|-----------|--------|
| **Image** | `<img src="url">` ✅ | `[Image: caption]` text | Stripped | `![caption](url)` if hosted |
| **Video** | Link + poster thumbnail | `[Video: caption]` text | Stripped | Link only |
| **Audio** | Link with icon | `[Audio: caption]` text | Stripped | Link only |
| **File** | Download link | `[File: title]` text | Stripped | Link only |

### Email Details
- `<img>` tags with hosted/preview URLs **work** in Gmail, Outlook, Apple Mail
- `data:` URIs **do NOT work** in Gmail/Outlook → must detect and skip or resolve
- `<video>`/`<audio>` tags **do NOT work** in email clients → render as link + thumbnail
- For email: images render inline, everything else becomes a styled link

### SMS/X Details
- No media rendering at all
- Replace each media reference with a text label: `[📸 caption]`, `[🎬 caption]`, etc.
- Keep it informational, don't lose the context

### Reddit Details
- Supports markdown images `![](url)` but only with hosted URLs
- Video/audio → link only

---

## 3. Pieces to Build (Broken Down)

### Piece A: `_resolve_media_in_markdown()` — Backend Function
**File:** `routes_messages.py`
**Purpose:** Find all `![...](media://...)` patterns in markdown content and resolve URIs.

```python
def _resolve_media_in_markdown(text: str, mode: str = "preview") -> str:
    """
    Resolve media:// URIs in markdown image syntax.
    
    mode:
      - "preview" → /api/content/media/{id}/preview (admin preview)
      - "email"   → same for now; future: public hosted URL
      - "strip"   → remove media, replace with text label
    """
```

**Handles:**
1. `![caption](media://id)` → resolve to preview URL or strip
2. `![video: cap](media://id)` → resolve or strip
3. `![audio: cap](media://id)` → resolve or strip
4. `![file: name](media://id)` → resolve or strip
5. Pass through `data:` and `https://` URLs unchanged

### Piece B: `_markdown_to_html()` — Add Image/Media Support
**File:** `routes_messages.py` (preview renderer) + `email_resend.py` (real adapter)

Currently handles: headers, bold, italic, links, hr, paragraphs.
**Add:**
1. Standard image: `![alt](url)` → `<img src="url" alt="alt" style="...">`
2. Video prefix: `![video: cap](url)` → styled link with 🎬 icon
3. Audio prefix: `![audio: cap](url)` → styled link with 🎵 icon  
4. File prefix: `![file: name](url)` → styled download link with 📎 icon

**Order matters:** Images must be processed BEFORE the link regex (since `![]()`
contains `[]()`).

### Piece C: `_build_sms_preview()` / `_build_x_preview()` — Strip Media
**File:** `routes_messages.py`

Add a strip step before text processing:
- `![caption](url)` → `[📸 caption]` (or just `[Image: caption]`)
- `![video: x](url)` → `[🎬 x]`
- `![audio: x](url)` → `[🎵 x]`
- `![file: x](url)` → `[📎 x]`

### Piece D: Vault Picker Mode for Messages
**File:** `_content.html` (shared picker JS)

Add a mode flag to the vault picker:
```javascript
let vaultPickerTarget = 'editor';  // 'editor' or 'messages'
```

When `target === 'messages'`:
- `vaultPickerInsert('embed')` → insert markdown at textarea cursor position
- The embed/attach distinction changes:
  - **Embed** = `![caption](media://id)` (inline in email)
  - **Attach** = `![file: name](media://id)` (download link in email)
- For video: `![video: name](media://id)`
- For audio: `![audio: name](media://id)`

### Piece E: "📎 Media" Button in Messages Toolbar
**File:** `_tab_content.html`

Add a button next to the variable insert row:
```html
<button class="btn" onclick="messagesOpenVaultPicker()" title="Insert media from vault">
    📎 Media
</button>
```

### Piece F: `messagesOpenVaultPicker()` — Bridge Function
**File:** `_messages.html`

```javascript
function messagesOpenVaultPicker() {
    vaultPickerTarget = 'messages';
    openVaultPicker();
}
```

### Piece G: `messagesInsertMedia()` — Markdown Insertion
**File:** `_messages.html`

```javascript
function messagesInsertMedia(mediaUri, filename, mimeCategory) {
    const textarea = document.getElementById('messages-edit-content');
    // Build markdown syntax based on category
    let prefix = '';
    if (mimeCategory === 'video') prefix = 'video: ';
    else if (mimeCategory === 'audio') prefix = 'audio: ';
    else if (mimeCategory === 'file') prefix = 'file: ';
    
    const md = `![${prefix}${filename}](${mediaUri})`;
    // Insert at cursor position
    insertAtCursor(textarea, md);
    messagesContentChanged();
}
```

### Piece H: Paste Handler on Textarea
**File:** `_messages.html`

```javascript
document.getElementById('messages-edit-content')
    .addEventListener('paste', async (e) => {
        const items = e.clipboardData?.items;
        if (!items) return;
        
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                const file = item.getAsFile();
                await messagesUploadAndInsert(file);
                return;
            }
        }
    });
```

### Piece I: `messagesUploadAndInsert()` — Upload + Insert
**File:** `_messages.html`

Uploads via `/api/content/media/editor-upload`, then inserts markdown:
- If inline (< 100KB): `![pasted](data:image/...;base64,...)`
- If vault (≥ 100KB): `![pasted](media://img_XXX)`
- Shows the upload toast (reused from EditorJS)
- Handles XHR progress, errors

### Piece J: Preview Pipeline Update
**File:** `routes_messages.py`

In `api_preview_message()`, before rendering:
1. `_render_variables()` — substitute `${{var}}` (already done)
2. **NEW:** `_resolve_media_in_markdown()` — rewrite `media://` URIs to preview URLs
3. `_markdown_to_html()` — convert to HTML (now with image support)

For email: full image rendering.
For SMS/X: strip media to text labels, then proceed.

---

## 4. Execution Order

| # | Piece | Depends On | Files Modified |
|---|-------|-----------|----------------|
| 1 | A — `_resolve_media_in_markdown()` | — | `routes_messages.py` |
| 2 | B — `_markdown_to_html()` image support | — | `routes_messages.py`, `email_resend.py` |
| 3 | C — Strip media for SMS/X/Reddit | A | `routes_messages.py` |
| 4 | J — Preview pipeline update | A, B | `routes_messages.py` |
| 5 | D — Vault picker mode flag | — | `_content.html` |
| 6 | E — Media button in toolbar | — | `_tab_content.html` |
| 7 | F — Bridge function | D, E | `_messages.html` |
| 8 | G — Markdown insertion | F | `_messages.html` |
| 9 | H — Paste handler | — | `_messages.html` |
| 10 | I — Upload + insert | H, G | `_messages.html` |

**Phases:**
- **Phase 1 (Backend):** Pieces A, B, C, J — Media resolves and renders correctly
- **Phase 2 (Vault Picker):** Pieces D, E, F, G — Pick from vault, insert markdown
- **Phase 3 (Paste Upload):** Pieces H, I — Paste image, auto-upload, insert

---

## 5. Blindspot Analysis

### ✅ Covered
- All 4 media types (image, video, audio, file)
- All 4 adapters (email, SMS, X, Reddit)
- Preview rendering with media resolution
- Vault picker reuse with mode flag
- Paste-to-upload for images
- Data URI passthrough for small images
- External URL passthrough

### ⚠️ Edge Cases to Handle
1. **`data:` URIs in email send** — Gmail/Outlook block them. At send time,
   small inlined images should either be left as-is (they'll be broken in some
   clients) or converted to CID attachments. **For now:** leave as-is, document
   the limitation. Future: Resend supports attachments for CID embedding.

2. **`media://` at real send time** — The tick engine renders templates and sends
   them. At that point, `media://` URIs need resolution. The resolver.py already
   handles decryption. We need to add media URL resolution to the real adapter
   pipeline. **For now:** resolve to preview URL (works if admin server is running).
   **Future:** resolve to hosted/public URL.

3. **Video paste** — Clipboard paste only works for images. Video/audio files must
   use the vault picker or the upload button. This is standard behavior.

4. **Template encryption + media refs** — If a template is encrypted and contains
   `media://` refs, the refs are stored encrypted. On decrypt + render, they resolve
   normally. No special handling needed.

5. **Markdown escaping** — What if a user types `![not media](regular text)`?
   The regex should only match URLs that look like `media://`, `data:`, or `http`.
   Other "URLs" pass through as text.

6. **Email image sizing** — `<img>` tags need `max-width: 100%` for responsive
   email layouts. The styled email template uses a 560px container, so images
   should be constrained.

7. **Adapter hints update** — The existing hints should mention media support:
   - Email: `📧 # Header → subject. Body → styled HTML. Images supported.`
   - SMS: `📱 Plain text. 160c/segment. Media stripped.`
   - X: `🐦 280 chars. No markdown. Media stripped.`
   - Reddit: `🤖 # Header → post title. Images if hosted.`

8. **Render order in `_markdown_to_html()`** — Image regex `![...](...)` MUST run
   before the link regex `[...](...)` since `![text](url)` contains `[text](url)`.
   If links are processed first, images get mangled.

9. **Multiple media on one line** — The regex must be non-greedy: `!\[.*?\]\(.*?\)`
   to handle multiple images on the same line (rare but possible).

10. **alt text with special chars** — Alt text in `![alt](url)` might contain
    brackets `]` or parens `)`. Use balanced matching or restrict alt text chars.
    **Pragmatic:** `!\[([^\]]*)\]\(([^)]+)\)` covers 99% of cases.
