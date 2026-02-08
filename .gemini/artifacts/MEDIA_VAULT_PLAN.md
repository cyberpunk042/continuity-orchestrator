# Media Vault — Implementation Plan

> Encrypted media storage with stage-based disclosure for continuity content.

**Status**: Phase 3 complete ✅  
**Date**: 2026-02-08  

---

## Overview

Add support for encrypted media files (images, PDFs, documents, videos) alongside
existing encrypted article content. Media files follow the same stage-based
visibility model: encrypted at rest, decrypted only at build time when the
disclosure stage threshold is met.

---

## Gap Analysis

### Layer 1: Storage & Encryption (`src/content/`)

| What Exists | What's Missing |
|-------------|---------------|
| `crypto.py` encrypts **JSON dicts** (articles) | No support for **binary files** (images, PDFs, videos) |
| `encrypt_content()` takes a Python dict | Need `encrypt_file()` that takes raw bytes |
| `decrypt_content()` returns a Python dict | Need `decrypt_file()` that returns raw bytes |
| Encrypted articles use JSON envelope | Binary files need a binary envelope (or sidecar JSON) |
| `CONTENT_ENCRYPTION_KEY` from `.env` | Same key — no change needed ✅ |
| `content/articles/` directory | Need `content/media/` directory |
| — | Need `content/media/manifest.json` for media registry |

**Gap details — Binary encryption:**

The current `encrypt_content()` serializes a dict to JSON, then encrypts. For 
binary files, we need a parallel path:

```python
# Current (articles only)
encrypt_content(data: dict, passphrase: str) -> dict   # JSON → encrypted JSON

# Needed (binary files)
encrypt_file(plaintext: bytes, passphrase: str) -> bytes  # raw bytes → encrypted bytes
decrypt_file(ciphertext: bytes, passphrase: str) -> bytes  # encrypted bytes → raw bytes
```

The cryptographic primitives are identical (AES-256-GCM, PBKDF2). The difference
is the envelope format:

- **Articles**: JSON envelope (`{"encrypted": true, "ciphertext": "...", ...}`)
- **Media files**: Binary envelope — prefix header with salt/IV/tag, then ciphertext

**Proposed binary format** (`.enc` files):

```
┌──────────────────────────────────────────────┐
│  Magic bytes: "COVAULT" (7 bytes)            │  ← Identifies the format
│  Version: 1 (1 byte)                         │
│  Original filename length: N (2 bytes, BE)   │
│  Original filename: N bytes (UTF-8)          │
│  MIME type length: M (2 bytes, BE)           │
│  MIME type: M bytes (UTF-8)                  │
│  Salt: 16 bytes                              │
│  IV: 12 bytes                                │
│  Tag: 16 bytes                               │
│  Ciphertext: remaining bytes                 │
└──────────────────────────────────────────────┘
```

This avoids large base64 overhead (~33% size increase) on potentially large files.

---

### Layer 2: Media Manifest

| What Exists | What's Missing |
|-------------|---------------|
| `content/manifest.yaml` for articles | No media manifest |
| `ArticleEntry` has `visibility.min_stage` | Media needs its own `min_stage` |
| `ArticleMeta` has `description`, `tags` | Media needs `mime_type`, `size_bytes`, `sha256` |

**Proposed**: `content/media/manifest.json`

```json
{
  "version": 1,
  "media": [
    {
      "id": "img_001",
      "original_name": "evidence-photo.jpg",
      "mime_type": "image/jpeg",
      "size_bytes": 845322,
      "sha256": "a1b2c3d4...",
      "encrypted": true,
      "min_stage": "PARTIAL",
      "referenced_by": ["evidence-report"],
      "uploaded_at": "2026-02-08T08:00:00Z",
      "caption": "Optional default caption"
    }
  ]
}
```

Why JSON not YAML: aligns with the binary nature of media operations, easier to
parse/update programmatically from both Python and JS.

**Integration with article manifest**: The article `manifest.yaml` stays as-is.
Media visibility is tracked in its own manifest. The site generator reads both.

---

### Layer 3: Article ↔ Media References

| What Exists | What's Missing |
|-------------|---------------|
| `EditorJSRenderer._render_image` takes `url` field | Only supports external URLs |
| Editor.js `image` block type registered | No `media://` URI resolution |
| No block types for PDF, video, audio | Need `attachment`, `video`, `audio` block types |

**Gap: URI Resolution**

Articles reference media via `media://id` URIs:

```json
{"type": "image", "data": {"url": "media://img_001", "caption": "Evidence"}}
```

The renderer must resolve this:
1. At **admin preview time**: `/api/content/media/img_001/preview` → decrypted on the fly
2. At **site build time**: `media://img_001` → `/media/evidence-photo.jpg` (decrypted file in public/)
3. At **restricted stage**: `media://img_001` → `🔒 [Media restricted]` placeholder

**Changes needed in `editorjs.py`**:
- `_render_image()` — check for `media://` prefix, resolve via media context
- Add `_render_attachment()` — PDF/document download block
- Add `_render_video()` — video embed block
- Add `_render_audio()` — audio player block
- Pass `media_resolver` callback to renderer (dependency injection)

---

### Layer 4: Site Generator (`src/site/generator.py`)

| What Exists | What's Missing |
|-------------|---------------|
| `build()` copies CSS, renders articles | No media decryption step |
| `_generate_articles()` loads article JSON | No media file processing |
| Articles dir: `public/articles/` | Need `public/media/` output |
| `deploy-site.yml` has `CONTENT_ENCRYPTION_KEY` | Same key works ✅ |

**Changes needed in `generator.py`**:

```python
def build(self, state, ...):
    # ... existing steps ...
    self._copy_css()
    
    # NEW: Decrypt and copy media files for the current stage
    self._process_media(stage)   # ← NEW
    
    context = self._build_context(state, ...)
    # ... rest of build ...
```

New method `_process_media(stage)`:
1. Load `content/media/manifest.json`
2. For each media entry where `STAGE_ORDER[stage] >= STAGE_ORDER[media.min_stage]`:
   - Decrypt `content/media/{id}.enc` → `public/media/{original_name}`
   - Record mapping: `id → /media/original_name` for article rendering
3. Pass media map into article rendering context

**Size concern**: The build step runs in GitHub Actions (ubuntu-latest).
Available disk is ~14GB, RAM ~7GB. Decrypting even hundreds of MB of media
is fine. The GitHub Pages 1GB limit is the real constraint.

---

### Layer 5: Admin API (`src/admin/routes_content.py`)

| What Exists | What's Missing |
|-------------|---------------|
| CRUD for articles (list, get, save, delete) | No media upload/list/delete endpoints |
| Encrypt/decrypt article endpoints | No media encrypt on upload |
| Encryption status check | Same ✅ |
| Content served as JSON | Media needs binary download for preview |

**New endpoints needed**:

```
POST   /api/content/media/upload       # Upload + encrypt a media file
GET    /api/content/media               # List all media from manifest
GET    /api/content/media/<id>          # Get media metadata
GET    /api/content/media/<id>/preview  # Decrypt + serve binary for admin preview
DELETE /api/content/media/<id>          # Delete media file + manifest entry
PATCH  /api/content/media/<id>          # Update metadata (min_stage, caption)
```

**Upload flow**:
1. Frontend sends file via `multipart/form-data`
2. Backend generates media ID (slug from filename + counter)
3. Encrypt file → `content/media/{id}.enc`
4. Compute SHA-256 of plaintext
5. Update `content/media/manifest.json`
6. Return `{ id, media_uri: "media://id" }` to editor

**Preview flow**:
1. Frontend requests `/api/content/media/{id}/preview`
2. Backend reads `.enc` file, decrypts in memory
3. Serves with correct `Content-Type` header
4. Used for admin panel preview only (never committed to public/)

**File size limits**:
- Tier 1 (inline): handled by article save, < 200KB base64 in JSON
- Tier 2 (repo): handled by upload endpoint, suggest 10MB max per file
- Flask default max: 16MB (configurable via `MAX_CONTENT_LENGTH`)

---

### Layer 6: Admin UI (templates/)

**⚠️ DEFERRED — Will rediscuss before implementing**

High-level needs:
- Media upload in content editor (drag & drop or file picker)
- Media browser/gallery (list, preview, delete)
- Stage assignment per media file
- Article references shown inline in editor

---

### Layer 7: .gitignore & Safety

| What Exists | What's Missing |
|-------------|---------------|
| `.env` ignored ✅ | Need to ignore plaintext media |
| `.env.vault` ignored ✅ | |
| `public/` ignored ✅ | Decrypted media in public/ won't be committed ✅ |
| — | Need to ignore `content/media/*.jpg`, `*.png`, etc. |
| — | Only `content/media/*.enc` and `manifest.json` tracked |

**Changes to `.gitignore`**:
```gitignore
# Media — only encrypted files tracked
content/media/*
!content/media/*.enc
!content/media/manifest.json
!content/media/README.md
```

---

### Layer 8: Documentation

| What Exists | What's Missing |
|-------------|---------------|
| `content/README.md` documents articles | No mention of media |
| `docs/ARCHITECTURE.md` lists modules | No media layer |
| Editor.js block types listed | `image` listed but not `attachment`/`video`/`audio` |

Updates needed:
- `content/README.md` — add media section
- `docs/ARCHITECTURE.md` — add media vault to diagram
- `content/media/README.md` — new file explaining media conventions

---

### Layer 9: CI/CD Pipeline

| What Exists | What's Missing |
|-------------|---------------|
| `deploy-site.yml` has `CONTENT_ENCRYPTION_KEY` ✅ | No code changes needed ✅ |
| `cron.yml` has `CONTENT_ENCRYPTION_KEY` ✅ | No code changes needed ✅ |
| `renew.yml` builds site ✅ | No code changes needed ✅ |
| `pip install ... cryptography` ✅ | Already installed ✅ |

**The pipeline is already compatible!** The `build-site` command already has
access to the encryption key. We just need the site generator to use it for
media files too.

---

## Implementation Order

### Phase 1: Storage Foundation (no UI) ✅
1. ✅ `src/content/crypto.py` — added `encrypt_file()` / `decrypt_file()` / `is_encrypted_file()` / `read_file_metadata()` (COVAULT binary format)
2. ✅ `src/content/media.py` — new module: `MediaManifest` + `MediaEntry` with load/save/query/mutate
3. ✅ `content/media/manifest.json` — empty manifest created
4. ✅ `.gitignore` — media safety rules (only `.enc`, `manifest.json`, `README.md` tracked)
5. ✅ `content/media/README.md` — conventions documented
6. ✅ `tests/test_file_crypto.py` — 35 tests for binary encryption
7. ✅ `tests/test_media_manifest.py` — 41 tests for manifest management

### Phase 2: Site Generator Integration ✅
5. ✅ `src/site/generator.py` — added `_process_media(stage)` and `_build_media_resolver()`
6. ✅ `src/site/editorjs.py` — updated `_render_image()` with `media://` resolution + restricted placeholders
7. ✅ `src/site/editorjs.py` — added `_render_attachment()`, `_render_video()`, `_render_audio()` block types
8. ✅ `src/content/media.py` — standalone media manifest (Phase 1), no merge with article manifest needed
9. ✅ `tests/test_editorjs_media.py` — 28 tests for media rendering
10. ✅ `tests/test_generator_media.py` — 10 tests for generator media integration

### Phase 3: Admin API ✅
9. ✅ `src/admin/routes_media.py` — new blueprint with upload, list, get, preview, delete, update endpoints
10. ✅ `src/admin/server.py` — registered `media_bp` blueprint at `/api/content/media`
11. ✅ `src/admin/server.py` — set `MAX_CONTENT_LENGTH = 16 MB` for upload limits
12. ✅ `tests/test_media_api.py` — 28 tests covering all 6 routes + error paths

### Phase 4: Admin UI (⏸ rediscuss first)
12. Content editor media upload integration
13. Media browser / gallery panel
14. Stage assignment per media

### Phase 5: Documentation
15. Update `content/README.md`
16. Update `docs/ARCHITECTURE.md`
17. Update `templates/README.md`

---

## Size Budget

| Component | Estimated Size |
|-----------|---------------|
| Repo media (all `.enc` files) | ≤ 200MB recommended |
| Single file max (Tier 2) | 10MB per upload |
| GitHub Pages output | ≤ 1GB total |
| In-memory decrypt (CI) | ~7GB available |

For larger files (> 10MB), Tier 3 (GitHub Releases) is the escape hatch,
but that's a separate future enhancement.

---

## Security Checklist

- [ ] Same `CONTENT_ENCRYPTION_KEY` for articles and media (single key to manage)
- [ ] Plaintext media never committed (`.gitignore` rules)
- [ ] Plaintext media never in `public/` repo (already gitignored)
- [ ] Media filenames in repo are opaque IDs (`img_001.enc`), not descriptive
- [ ] SHA-256 integrity check after decryption
- [ ] Upload endpoint validates file type and size
- [ ] Preview endpoint requires local access only (127.0.0.1)
- [ ] Binary format includes filename in encrypted payload (can't be guessed)

---

## Open Questions

1. **Max file size for Tier 2?** Suggested 10MB. User may want higher.
2. **Media ID format?** `{type}_{sequential}` (e.g., `img_001`) vs hash-based.
3. **Inline base64 (Tier 1)?** Worth implementing or skip for simplicity?
4. **Progressive disclosure for media?** Same article, different images per stage?
   e.g., redacted version at PARTIAL, full at FULL.
5. **Video handling?** Embed player or just download link? Video files are typically
   too large for Tier 2 — defer to Tier 3?
