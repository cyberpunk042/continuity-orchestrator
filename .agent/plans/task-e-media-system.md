# Task E: Media System — Complete Implementation Plan

## Core Insight

**Embed vs Attach is a per-insertion choice, not a file property.**

The same video file can appear as:
- A `video` block → `<video controls>` player (embedded)
- An `attachment` block → 📎 download link (attached)

The same image can be:
- An `image` block → `<img>` rendered inline (embedded)
- An `attachment` block → 📎 download link (attached)

This maps cleanly to the 4 block types the renderer already supports:

| Block type | Renders as | Used for |
|-----------|-----------|----------|
| `image` | `<figure><img>` | Embedded images |
| `video` | `<figure><video>` | Embedded video player |
| `audio` | `<div><audio>` | Embedded audio player |
| `attachment` | `<div><a download>` | Download link (ANY file type) |

**Every file can be inserted as `attachment`.** Only images/video/audio have
an *additional* embed option.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    ADMIN EDITOR                           │
│                                                          │
│  ┌─────────────────┐    ┌──────────────────────────────┐ │
│  │ EditorJS         │    │ Vault Picker Modal           │ │
│  │                  │    │                              │ │
│  │ Block types:     │←───│ [📸 Images] [🎬 Video] ...  │ │
│  │ • image    ✅    │    │                              │ │
│  │ • video    🆕    │    │ ┌──┐ ┌──┐ ┌──┐ ┌──┐        │ │
│  │ • audio    🆕    │    │ │  │ │  │ │  │ │  │ thumb   │ │
│  │ • attachment 🆕  │    │ └──┘ └──┘ └──┘ └──┘ grid   │ │
│  │                  │    │                              │ │
│  │ uploadByFile ────│──→ │ [▶ Embed] [📎 Attach]       │ │
│  └─────────────────┘    └──────────────────────────────┘ │
│           │                          │                    │
│     save/load                  insert block               │
│           ↓                          ↓                    │
│  contentRewriteMediaUrls    editor.blocks.insert()        │
│  (media:// ↔ preview URL)                                │
└──────────────────────────────────────────────────────────┘
           │
           ↓ save to disk
┌──────────────────────────────────────────────────────────┐
│                   STORAGE PIPELINE                        │
│                                                          │
│  Upload → Optimize → Encrypt → Store → Manifest          │
│  (any     (image     (AES      (inline   (media.py)      │
│   type)    only)     -256-GCM)  /git/                    │
│                                 large)                   │
└──────────────────────────────────────────────────────────┘
           │
           ↓ build-site
┌──────────────────────────────────────────────────────────┐
│                  SITE RENDER PIPELINE                     │
│                                                          │
│  editorjs.py:                                            │
│  • _render_image      → <figure><img>      ✅ exists     │
│  • _render_video      → <figure><video>    ✅ exists     │
│  • _render_audio      → <div><audio>       ✅ exists     │
│  • _render_attachment  → <div><a download>  ✅ exists     │
│                                                          │
│  media:// → resolved URL (visible) or lockbox (restricted)│
│                                                          │
│  CSS:                                                    │
│  • .video-block        ❓ needs check                    │
│  • .audio-block        ❓ needs check                    │
│  • .attachment         ❓ needs check                    │
└──────────────────────────────────────────────────────────┘
```

---

## Implementation Steps (Ordered)

Everything that needs to be done, in dependency order.
Each step lists what it touches and what it produces.

---

### Step 1: Expand MIME prefix map + general upload

**Files**: `routes_media.py`

Currently only `image/`, `video/`, `audio/`, `application/pdf` have prefixes.
Add full coverage and make the general `/upload` endpoint call
`_upload_to_release_bg()` for large files (currently only `editor-upload` does).

```python
MIME_PREFIX_MAP = {
    "image/":              "img",
    "video/":              "vid",
    "audio/":              "aud",
    "application/pdf":     "doc",
    "text/":               "txt",
    "application/json":    "dat",
    "message/rfc822":      "eml",
    # everything else:     "file"
}
```

**Changes**:
- Expand `MIME_PREFIX_MAP` + update `_id_prefix_for_mime()` fallback
- In `api_upload_media()`, add release backup for large files
- Accept file extensions: `.eml`, `.msg`, `.json`, `.txt`, `.csv`, `.md`

**Produces**: Any file type can be uploaded, gets a proper ID, and large
files are backed up to GitHub Releases.

---

### Step 2: Extend `contentRewriteMediaUrls` for all block types

**Files**: `_content.html`

Currently only rewrites `image` blocks. Must also handle `video`, `audio`,
and `attachment` blocks for admin preview.

```javascript
// Current: only image
if (block.type !== 'image') continue;

// New: handle all media block types
const urlPaths = {
    'image':      ['file.url'],
    'video':      ['url', 'poster'],
    'audio':      ['url'],
    'attachment':  ['url'],
};
```

For each block type, rewrite the relevant URL field(s) between
`media://` ↔ `/api/content/media/{id}/preview`.

**Note**: `video.poster` is also a `media://` URI that needs rewriting.

**Produces**: All media block types display correctly in the admin editor
preview and save correctly with `media://` URIs.

---

### Step 3: Custom EditorJS block tools

**Files**: New JS in `_content.html` or a separate `_editor_tools.html`

Need 3 custom EditorJS tools since no official CDN packages exist:

#### 3a: VideoTool
```javascript
class VideoTool {
    static get toolbox() {
        return { title: 'Video', icon: '🎬' };
    }
    constructor({ data }) {
        this.data = data || {};
    }
    render() {
        // Show <video> player if URL exists, or placeholder
    }
    save(el) {
        return { url: this.data.url, caption: this.data.caption, poster: this.data.poster };
    }
}
```

Data format (matches renderer expectations):
```json
{ "url": "media://vid_001", "caption": "Deposition video", "poster": "media://img_002" }
```

#### 3b: AudioTool
```json
{ "url": "media://aud_001", "caption": "Phone recording" }
```

#### 3c: AttachmentTool
```json
{ "url": "media://doc_001", "title": "Contract.pdf", "size": 845322 }
```

**Key constraint**: These tools must be read-only-ish in the editor. The
vault picker handles selection. The tool just renders a representation and
saves the data. Caption/title can be edited inline.

**Produces**: EditorJS can now render and save all 4 block types.

---

### Step 4: Vault picker modal

**Files**: `_content.html` (or new `_vault_picker.html` template)

The centerpiece UX component. A modal that:

1. **Opens** via a "📎 Insert Media" button above the EditorJS editor
2. **Loads** all media entries from `/api/content/media`
3. **Shows** a filterable grid with tabs:
   - 📸 Images (thumbnails from preview endpoint)
   - 🎬 Videos (icon + name + duration if available)
   - 🎵 Audio (icon + name)
   - 📄 Files (icon + name + size)
   - ✨ All (everything)
4. **On selection**, shows the insert mode choice:
   - **▶ Embed** (only for image/video/audio) — inserts native block type
   - **📎 Attach** (all types) — inserts `attachment` block
5. **Inserts** the block into EditorJS at the current position via
   `contentEditor.blocks.insert(type, data)`
6. **Closes** the modal

**Also supports upload**: A "📤 Upload new" button in the modal that:
- Opens a file picker (accepts all file types)
- Uploads via `/api/content/media/upload`
- After upload, the new file appears in the grid and can be selected

**Metadata auto-populated on insert**:
- `attachment`: `title` = original filename, `size` = size_bytes
- `video`/`audio`: `caption` = original filename (editable)
- `image`: `caption` = "" (user fills in)

**Produces**: Users can browse, pick, and insert any vault media into
an article, choosing embed or attach for each insertion.

---

### Step 5: Wire existing Image tool upload to vault picker

**Files**: `_content.html`

The existing `@editorjs/image` tool's `uploadByFile` works fine for new
images. But we should also add a connection so that when you click the
Image tool's "By URL" mode, there's a hint or button to open the vault
picker.

**Alternative**: Just rely on the vault picker for existing images and
keep the Image tool for quick drag-drop uploads. The two paths coexist:
- Drag an image onto the editor → `uploadByFile` → inline or vault
- Click "📎 Insert Media" → vault picker → embed or attach

This step may be minimal — just ensuring both paths work without conflict.

**Produces**: Seamless image insertion via either path.

---

### Step 6: Editor upload for non-image files

**Files**: `routes_media.py`, `_content.html`

Currently `editor-upload` is image-only (optimizes, converts to WebP).
Add a generic `editor-upload-file` endpoint (or extend the existing one)
that handles any file type:

- Images: existing optimization pipeline
- Everything else: straight to vault (no optimization), proper MIME prefix

This powers the "📤 Upload new" button inside the vault picker modal.

Could simply reuse the existing `/api/content/media/upload` endpoint since
it already accepts any file type. The picker modal just calls that.

**Produces**: Upload any file type from within the editor flow.

---

### Step 7: Site CSS for media blocks

**Files**: Site template CSS (needs investigation)

Check and ensure CSS classes exist and look good:
- `.video-block` — responsive video container
- `.audio-block` — styled audio player wrapper
- `.attachment` — download card with icon, title, size
- `.attachment-link`, `.attachment-icon`, `.attachment-title`, `.attachment-size`

**Produces**: Media renders beautifully on the published site.

---

### Step 8: ffmpeg optimization for video/audio (Phase 2 — optional)

**Files**: New `media_optimize_av.py`

If enabled (ffmpeg available), auto-compress:
- Video: re-encode to H.264/VP9, set max resolution, bitrate cap
- Audio: normalize loudness, compress to AAC/Opus

**Configuration**: `MEDIA_OPTIMIZE_AV=true` in `.env`, only runs if
`ffmpeg` binary is found on PATH.

**Decision**: Defer to Phase 2. Videos/audio stored raw for now.
Files over 2 MB go to `large/` tier and get backed to GitHub Releases.

---

## Data Format Summary

All block types and their JSON structure in article files:

```json
{
    "type": "image",
    "data": {
        "file": { "url": "media://img_001" },
        "caption": "Evidence photo",
        "stretched": false,
        "withBorder": false,
        "withBackground": false
    }
}
```

```json
{
    "type": "video",
    "data": {
        "url": "media://vid_001",
        "caption": "Deposition footage",
        "poster": "media://img_002"
    }
}
```

```json
{
    "type": "audio",
    "data": {
        "url": "media://aud_001",
        "caption": "Recorded phone call"
    }
}
```

```json
{
    "type": "attachment",
    "data": {
        "url": "media://doc_001",
        "title": "Contract_Final.pdf",
        "size": 845322
    }
}
```

---

## File Impact Map

| File | Steps | Changes |
|------|-------|---------|
| `routes_media.py` | 1, 6 | MIME map, large backup in upload, health + restore endpoints |
| `routes_content.py` | 2 | `_extract_media_info` handles video/audio/attachment captions |
| `_content.html` | 2, 3, 4, 5 | URL rewriting, custom tools, modal, wiring |
| `media_optimize.py` | — | No changes (images already handled) |
| `media.py` | — | No changes (manifest already universal) |
| `crypto.py` | — | No changes (encryption already universal) |
| `editorjs.py` | — | No changes (renderers already complete) |
| Site CSS | 7 | Add/verify media block styles |

---

## Execution Checklist

- [x] **Step 1**: Expand MIME prefix map + release backup in general upload
- [x] **Step 2**: Extend `contentRewriteMediaUrls` for video/audio/attachment
- [x] **Step 3**: Custom EditorJS tools (VideoTool, AudioTool, AttachmentTool)
- [x] **Step 4**: Vault picker modal (browse, filter, embed/attach choice)
- [x] **Step 5**: Wire Image tool + vault picker coexistence
- [x] **Step 6**: Upload any file type from within editor flow
- [x] **Step 7**: Site CSS for all media block types
- [ ] **Step 8**: (Phase 2) ffmpeg optimization for video/audio

Steps 1-2 are backend/plumbing. Steps 3-4 are the big UX work.
Steps 5-6 are wiring. Step 7 is polish. Step 8 is future.

---

## Decisions Made

1. ✅ **Embed vs Attach** = different block types, same file. User chooses
   at insertion time via the vault picker.
2. ✅ **Email files** = stored as downloadable attachments (no inline parsing).
3. ✅ **ffmpeg compression** = deferred to Phase 2.
4. ✅ **Vault picker includes upload** = combined browse + upload experience.
5. ✅ **Custom EditorJS tools** = minimal tools focused on display + save,
   not complex inline editing. Caption/title editable, URL managed by picker.
6. ✅ **Large file restore** = `/api/content/media/restore-large` downloads
   missing gitignored files from `media-vault` GitHub Release.
7. ✅ **Health check** = `/api/content/media/health` reports missing files,
   storage tiers, and `gh` CLI availability.
8. ✅ **Caption extraction** = `_extract_media_info()` captures captions/titles
   from all block types (video, audio, attachment), not just images.
