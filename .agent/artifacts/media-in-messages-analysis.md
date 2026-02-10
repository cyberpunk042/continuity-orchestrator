# Media Insertion in Messages Editor — Analysis

## Current Architecture

### Templates
Messages use **markdown templates** (`.md`/`.txt`) edited in a plain `<textarea>`.
The markdown is converted to HTML by `_markdown_to_html()` for email, or stripped down for SMS/X/Reddit.

### Existing Media Infrastructure
| Component | Location | What it does |
|-----------|----------|--------------|
| Upload endpoint | `POST /api/content/media/upload` | Upload file → vault, returns `media_uri` |
| Editor upload | `POST /api/content/media/editor-upload` | Hybrid: <100KB → `data:` URI, ≥100KB → vault `media://id` |
| Fetch URL | `POST /api/content/media/editor-fetch-url` | Download external image → upload to vault |
| Preview API | `GET /api/content/media/<id>/preview` | Serve decrypted media for admin preview |
| Vault picker modal | `#vault-picker-overlay` | Shared modal, currently wired only to EditorJS |

### How EditorJS Handles Media
1. **Paste/drop image** → EditorJS `ImageTool` → calls `editor-upload` → gets back `{file: {url: "/api/…/preview"}}` → displays inline
2. **Paste URL** → `uploadByUrl` → calls `editor-fetch-url` → same flow
3. **Vault picker** → opens modal → picks media → inserts an EditorJS block
4. **On save** → `contentRewriteMediaUrls(data, 'toMedia')` rewrites preview URLs back to `media://id`
5. **On load** → `contentRewriteMediaUrls(data, 'toPreview')` rewrites `media://id` to preview URLs

### Markdown → HTML Pipeline
`_markdown_to_html()` currently handles: headers, bold, italic, links, hr, paragraphs.
**It does NOT handle `![alt](url)` markdown images.**

### Email Rendering
Uses `resend.Emails.send({html: ..., text: ...})`. The HTML body is built from `_build_styled_email()`.
Images via `<img>` tags with absolute URLs **will work** in most email clients.
`data:` URIs do **NOT** work in most email clients (Gmail, Outlook block them).
`media://` URIs make no sense at send time — must be resolved to real URLs.

---

## Per-Adapter Media Support

| Adapter | Format | Image Support | Approach |
|---------|--------|---------------|----------|
| **Email** | HTML | ✅ `<img>` tags | Best: `media://id` → resolved to hosted URL at send time. For preview: `/api/content/media/id/preview`. Inline `data:` URIs only work in some clients. |
| **SMS** | Plain text | ❌ No images | Images stripped. Could include a URL link instead. |
| **X / Twitter** | Plain text | ⚠️ Partial | X API supports media uploads separately, but our adapter doesn't currently. For now: stripped or linked. |
| **Reddit** | Markdown | ⚠️ Partial | Reddit markdown supports `![](url)` but requires hosted URLs. `media://` must be resolved. |

---

## What Needs to Happen

### 1. Markdown Image Syntax in Templates
Templates should use standard markdown images: `![caption](media://img_001)`

This is the **right format** because:
- Templates are markdown files — standard syntax
- At render time, `media://` URIs get resolved to real URLs
- Works naturally with the existing `_render_variables()` pipeline

### 2. `_markdown_to_html()` — Add Image Support
Both the preview function and the real email adapter need to convert:
```
![caption](url) → <img src="url" alt="caption" style="max-width:100%;...">
```

### 3. Media Resolution at Render Time
A new step in the render pipeline should resolve `media://id` URIs to real URLs.
- **Admin preview:** → `/api/content/media/id/preview`
- **Email send:** → public URL (if hosted) or inline base64 (if small)
- **SMS/X:** → strip images or insert link-only

### 4. Insert Media into Textarea
Two insertion methods:

#### a) Vault Picker (button click)
- Add a "📎 Media" button next to the variable insert buttons
- Reuse the existing vault picker modal
- On select: insert `![filename](media://id)` at cursor position
- No embed/attach distinction needed — it's always markdown syntax

#### b) Paste Handler (paste event on textarea)
- Listen for `paste` event on the textarea
- If clipboard has image data (file), upload via `editor-upload` endpoint
- Insert `![pasted-image](media://id)` at cursor (or `![](data:…)` if inlined)
- Show the upload toast (reuse from EditorJS flow)

### 5. Live Preview Support
The preview API (`/api/content/messages/preview`) already calls `_markdown_to_html()`.
Once we add image support to that function, `![](media://id)` will render in the email preview iframe.
For the preview, `media://id` should be rewritten to `/api/content/media/id/preview`.

---

## Implementation Plan (Ordered)

### Phase 1: Backend — Image rendering support
1. **Add markdown image regex** to `_markdown_to_html()` in `routes_messages.py`
2. **Add `media://` resolution** for preview (rewrite to `/api/content/media/id/preview`)
3. **Add `media://` resolution** to the real email adapter `_markdown_to_html()`
4. **Strip images** for SMS/X/Reddit adapters (graceful degradation)

### Phase 2: Frontend — Vault picker for messages
5. **Add "📎 Media" button** next to variable insert buttons
6. **Wire vault picker** to work in message context (not just EditorJS)
   - Need a mode flag: `vaultPickerMode = 'editor' | 'messages'`
   - When mode = 'messages', insert markdown syntax instead of EditorJS block
7. **Insert function**: `messagesInsertMedia(mediaUri, filename)` — inserts `![filename](mediaUri)` at cursor

### Phase 3: Frontend — Paste-to-upload
8. **Paste handler** on textarea: intercept image paste
9. **Upload via `editor-upload`**: reuse the same endpoint
10. **Insert result**: `![pasted-image](media://id)` or `![](data:...)` for small files
11. **Upload toast**: reuse the same floating progress toast

### Phase 4: Polish
12. **Preview images in email preview**: verify they render correctly
13. **Adapter-aware hints**: update adapter hints to mention image support (email: ✅, SMS: ❌)
