# Encrypted Content & Editor — Implementation Plan

> **Created**: 2026-02-07  
> **Status**: Planning  
> **Goal**: Allow articles to be stored encrypted in the repository and edited visually from the admin dashboard

---

## Problem Statement

Content articles (`content/articles/*.json`) are stored in **plaintext** Editor.js JSON.
On a public repository, anyone can read the disclosure content before
escalation triggers — **the entire security model is undermined**.

We need:
1. **Encrypted article storage** — articles committed as encrypted blobs
2. **Transparent decryption** — `build-site` and admin dashboard decrypt on-the-fly
3. **Visual editor** — Editor.js embedded in the admin dashboard for authoring
4. **Encryption at save time** — user chooses plaintext or encrypted per article
5. **Retroactive encryption** — convert existing plaintext articles to encrypted

---

## Architecture Decisions

### Crypto Approach: AES-256-GCM via `cryptography`

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Algorithm** | AES-256-GCM | Authenticated encryption (tamper-proof), industry standard |
| **Library** | `cryptography` (PyCA) | Audited, maintained, standard for Python crypto |
| **Key derivation** | PBKDF2-SHA256 (100k iterations) | Passphrase → AES key; human-friendly secret |
| **Key scope** | One master key for all articles | Simpler key management; if the secret leaks, all content is compromised regardless |
| **Secret name** | `CONTENT_ENCRYPTION_KEY` | Stored in `.env` locally, GitHub Secrets for CI |
| **Nonce/IV** | Random 12 bytes per encryption | Generated fresh each save; stored with ciphertext |
| **Salt** | Random 16 bytes per encryption | Stored with ciphertext; ensures different derived keys per file even with same passphrase |

**Why not Fernet?** Fernet uses AES-128-CBC + HMAC (older construct), is Python-specific,
and doesn't interoperate with other ecosystems. AES-256-GCM is the modern standard used
by TLS, Wi-Fi, and most encryption libraries across languages.

### File Format

Encrypted articles remain `.json` files but with a distinct envelope:

```json
{
  "encrypted": true,
  "version": 1,
  "algorithm": "aes-256-gcm",
  "kdf": "pbkdf2-sha256",
  "kdf_iterations": 100000,
  "salt": "<base64-encoded-16-bytes>",
  "iv": "<base64-encoded-12-bytes>",
  "tag": "<base64-encoded-16-bytes>",
  "ciphertext": "<base64-encoded-encrypted-json>"
}
```

**Detection**: Any JSON file with `"encrypted": true` at the top level is treated
as encrypted. This means:
- No file extension changes needed
- `manifest.yaml` works unchanged (references slugs, not file formats)
- Auto-discovery in `ContentManifest._from_dict()` works unchanged (globs `*.json`)
- Mixed mode is natural: `about.json` (plaintext) + `disclosure.json` (encrypted)

### Editor.js Integration

Editor.js via **CDN** (jsDelivr) — no build step needed, consistent with the
project's no-build-tools philosophy. Tools loaded:
- `@editorjs/editorjs` (core)
- `@editorjs/header`
- `@editorjs/list`
- `@editorjs/quote`
- `@editorjs/code`
- `@editorjs/table`
- `@editorjs/warning`
- `@editorjs/delimiter`

---

## Integration Points (Codebase Analysis)

These are the **exact files and functions** that need modification:

### Reads from `content/articles/*.json`

| Location | Function | What it does | Change needed |
|----------|----------|-------------|---------------|
| `src/site/generator.py:396` | `SiteGenerator._generate_articles()` | Loads `{slug}.json`, calls `renderer.render_file()` | Intercept: check `encrypted` flag → decrypt before render |
| `src/site/editorjs.py:110` | `EditorJSRenderer.render_file()` | `json.loads(path.read_text())` | No change — receives already-decrypted dict |
| `src/site/editorjs.py:284` | `ContentManager.list_articles()` | Globs `*.json`, reads each | Detect encrypted articles, show metadata (can't read content without key) |
| `src/site/editorjs.py:313` | `ContentManager.get_article()` | Reads `{slug}.json`, renders HTML | Decrypt before render |
| `src/site/manifest.py:185` | `ContentManifest._from_dict()` | Auto-discovers `*.json` for slugs | Works unchanged (just needs `.json` extension) |

### Writes to `content/articles/*.json`

| Location | What | Change needed |
|----------|------|---------------|
| Currently: manual file creation | User creates JSON files by hand | New: admin dashboard writes files via API |

### Admin dashboard

| Location | What | Change needed |
|----------|------|---------------|
| `src/admin/templates/partials/_nav.html` | Tab navigation | Add "📝 Content" tab |
| `src/admin/templates/` | Tab content templates | Add `partials/_tab_content.html` |
| `src/admin/templates/scripts/` | Tab JS logic | Add `scripts/_content.html` |
| `src/admin/routes_*.py` | API routes | Add `routes_content.py` |
| `src/admin/server.py` | Blueprint registration | Register content blueprint |
| `src/admin/templates/partials/_head.html` | Head section | Add Editor.js CDN scripts |

### Configuration

| Location | What | Change needed |
|----------|------|---------------|
| `.env.example` | Env var documentation | Add `CONTENT_ENCRYPTION_KEY` |
| `pyproject.toml` | Dependencies | Add `cryptography` to optional `[security]` group |
| `docs/CONFIGURATION.md` | Config docs | Document new env var |

### CLI

| Location | What | Change needed |
|----------|------|---------------|
| `src/cli/` | CLI commands | Add `content.py` with encrypt/decrypt/keygen commands |
| `src/main.py` | CLI group registration | Register content commands |

---

## Phases

### Phase 1: Crypto Module (`src/content/crypto.py`)

**Goal**: Pure Python module for encrypt/decrypt, zero side effects, fully testable.

**New file**: `src/content/crypto.py`

```python
# Public API:
def generate_key() -> str
    """Generate a new CONTENT_ENCRYPTION_KEY (32-char passphrase)."""

def encrypt_content(data: dict, passphrase: str) -> dict
    """Encrypt Editor.js JSON → envelope dict."""

def decrypt_content(envelope: dict, passphrase: str) -> dict
    """Decrypt envelope dict → Editor.js JSON."""

def is_encrypted(data: dict) -> bool
    """Check if a JSON dict is an encrypted envelope."""

def get_encryption_key() -> Optional[str]
    """Read CONTENT_ENCRYPTION_KEY from environment."""
```

**New file**: `src/content/__init__.py`

**Dependencies**: `cryptography` added to `pyproject.toml` under `[project.optional-dependencies.security]`

**Tests**: `tests/test_content_crypto.py`
- `test_encrypt_decrypt_roundtrip` — encrypt, then decrypt, verify identical
- `test_is_encrypted_positive` — encrypted envelope returns True
- `test_is_encrypted_negative` — normal Editor.js JSON returns False
- `test_wrong_key_fails` — decrypt with wrong passphrase raises error
- `test_different_encryptions_differ` — same content encrypted twice produces different ciphertext (random IV/salt)
- `test_tampered_ciphertext_fails` — modified ciphertext raises authentication error
- `test_generate_key_entropy` — generated keys have sufficient randomness

**Deliverable**: Working crypto with 100% test coverage. No other files changed.

---

### Phase 2: Pipeline Integration (build-site, ContentManager)

**Goal**: `build-site` transparently decrypts encrypted articles during rendering.

**Modifications**:

1. **`src/site/generator.py` → `_generate_articles()`** (line ~396)
   - Before `renderer.render_file(content_path)`:
   - Read JSON, check `is_encrypted()`
   - If encrypted: `decrypt_content()` using `get_encryption_key()`
   - Pass decrypted dict to `renderer.render()` (not `render_file()`)
   - If not encrypted: existing path (unchanged)

2. **`src/site/editorjs.py` → `ContentManager.get_article()`** (line ~313)
   - Same pattern: read JSON → check encrypted → decrypt if needed → render

3. **`src/site/editorjs.py` → `ContentManager.list_articles()`** (line ~284)
   - For encrypted articles: still extract slug from filename
   - Add `"encrypted": True` to the returned metadata dict
   - Title: use slug-based title (can't read content without key)
   - If key is available: decrypt to get real title from first header block

**New helper** in `src/content/crypto.py`:
```python
def load_article(path: Path, passphrase: Optional[str] = None) -> dict:
    """Load an article file, decrypting if needed."""
```

**Tests**: `tests/test_content_pipeline.py`
- `test_build_site_with_encrypted_article` — encrypted article renders correctly
- `test_build_site_with_mixed_articles` — plaintext + encrypted both render
- `test_build_site_no_key_skips_encrypted` — graceful handling when key is missing
- `test_content_manager_list_shows_encrypted_badge`
- `test_content_manager_get_decrypts`

**Deliverable**: `python -m src.main build-site` works with encrypted articles. Existing tests still pass.

---

### Phase 3: CLI Commands (`src/cli/content.py`)

**Goal**: Command-line tools for key management and bulk encryption/decryption.

**New file**: `src/cli/content.py`

```
Commands:
  content-keygen     Generate a new CONTENT_ENCRYPTION_KEY
  content-encrypt    Encrypt an article (or all articles)
  content-decrypt    Decrypt an article (or all articles)
  content-status     Show encryption status of all articles
```

**Command details**:

```bash
# Generate a key
python -m src.main content-keygen
# → Generated key: xK9m2... (copy to .env or GitHub Secrets)

# Encrypt a specific article
python -m src.main content-encrypt --slug full_disclosure
# → ✓ Encrypted content/articles/full_disclosure.json

# Encrypt all plaintext articles (except those with min_stage: OK)
python -m src.main content-encrypt --all --skip-public
# → ✓ Encrypted 3 of 4 articles (skipped 1 public)

# Show status
python -m src.main content-status
# → about.json          plaintext  (min_stage: OK)
# → full_disclosure.json 🔒 encrypted (min_stage: FULL)

# Decrypt for debugging
python -m src.main content-decrypt --slug full_disclosure --dry-run
# → [shows decrypted content without writing to disk]
```

**Registration**: Add to `src/main.py` CLI group.

**Tests**: `tests/test_cli_content.py`
- Test each command with `CliRunner`
- Test `--dry-run` doesn't modify files
- Test `--skip-public` logic

**Deliverable**: Full CLI for key management and encryption operations.

---

### Phase 4: Content Editor Tab (Admin Dashboard)

**Goal**: Visual Editor.js editor in the admin dashboard for creating, editing,
and managing articles with encryption toggle.

This is the largest phase. Break into sub-phases:

#### Phase 4a: Backend Routes (`src/admin/routes_content.py`)

**New file**: `src/admin/routes_content.py`

```python
# API endpoints:
GET  /api/content/articles          # List all articles with metadata
GET  /api/content/articles/<slug>   # Get article content (decrypted)
POST /api/content/articles/<slug>   # Save article content
DELETE /api/content/articles/<slug> # Delete article
POST /api/content/articles/<slug>/encrypt   # Encrypt this article
POST /api/content/articles/<slug>/decrypt   # Decrypt this article (store plaintext)
GET  /api/content/encryption-status         # Is CONTENT_ENCRYPTION_KEY set?
POST /api/content/keygen                    # Generate and return a new key
```

**Response format** for GET `/api/content/articles`:
```json
{
  "articles": [
    {
      "slug": "about",
      "title": "About my-deadman",
      "encrypted": false,
      "min_stage": "OK",
      "include_in_nav": true,
      "description": "Project overview"
    },
    {
      "slug": "full_disclosure",
      "title": "Full Disclosure",
      "encrypted": true,
      "min_stage": "FULL",
      "include_in_nav": true,
      "description": null
    }
  ],
  "encryption_available": true
}
```

**Response format** for GET `/api/content/articles/<slug>`:
```json
{
  "slug": "about",
  "title": "About",
  "encrypted": false,
  "content": { "time": ..., "blocks": [...], "version": "2.28.0" },
  "manifest_entry": { "min_stage": "OK", ... }
}
```

**Blueprint registration** in `src/admin/server.py`.

**Tests**: `tests/test_routes_content.py`

#### Phase 4b: Frontend — Article List & Editor UI

**New files**:
- `src/admin/templates/partials/_tab_content.html` — HTML structure
- `src/admin/templates/scripts/_content.html` — JavaScript logic

**HTML structure** (`_tab_content.html`):
```
┌──────────────────────────────────────────────────────┐
│  📝 Content                                          │
├──────────────────────────────────────────────────────┤
│                                                      │
│  Encryption Key: ✅ Configured  [Generate Key]       │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ Articles                          [+ New]    │    │
│  ├──────────────────────────────────────────────┤    │
│  │ 📄 About             OK     plaintext        │    │
│  │ 🔒 Full Disclosure   FULL   encrypted        │    │
│  │ 🔒 Notice            PARTIAL encrypted       │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  ── Editor ──────────────────────────────────────    │
│  │                                              │    │
│  │  [Editor.js instance here]                   │    │
│  │                                              │    │
│  ├──────────────────────────────────────────────┤    │
│  │ Save as: (•) Encrypted  ( ) Plaintext        │    │
│  │ [Save]  [Discard]  [Delete]                  │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
└──────────────────────────────────────────────────────┘
```

**JS logic** (`_content.html`):
- Load article list from API on tab activation
- Click article → load into Editor.js
- Editor.js `save()` → POST to API with encryption preference
- New article dialog (slug + title)
- Encrypt/decrypt toggle per article
- Visual indicators: 🔒/📄 badges, stage colors

**Editor.js loading** (in `_head.html`):
```html
<!-- Editor.js (loaded only when content tab is active) -->
<script src="https://cdn.jsdelivr.net/npm/@editorjs/editorjs@2.30/dist/editorjs.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@editorjs/header@2.8/dist/header.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@editorjs/list@1.9/dist/list.umd.min.js"></script>
<!-- ... other tools -->
```

**Tab registration**:
- Add button in `_nav.html`
- Add `switchTab('content')` handler in `_tabs.html`
- Add include in `index.html`

#### Phase 4c: Manifest Editing

When saving an article through the editor, the API should also update
`content/manifest.yaml` if the article isn't already listed:
- Auto-add new articles to the manifest
- Allow editing `min_stage`, `include_in_nav`, `pin_to_top` from the UI
- Show a small metadata panel below the editor

---

### Phase 5: Configuration & Documentation

**Goal**: Update all configuration and documentation files.

**Files to update**:
- `.env.example` — add `CONTENT_ENCRYPTION_KEY` with documentation
- `pyproject.toml` — add `cryptography` to `[security]` deps
- `docs/CONFIGURATION.md` — document the encryption feature
- `docs/ARCHITECTURE.md` — add content encryption to the overview
- `docs/ROADMAP.md` — mark as Phase H
- `content/README.md` — update with encryption instructions
- `SECURITY.md` — add content encryption best practices

---

## Dependency Chain

```
Phase 1 (Crypto Module)
    ↓
Phase 2 (Pipeline Integration)     Phase 3 (CLI Commands)
    ↓                                  ↓
Phase 4a (Backend Routes)    ←─── uses crypto module
    ↓
Phase 4b (Frontend Editor UI)
    ↓
Phase 4c (Manifest Editing)
    ↓
Phase 5 (Docs & Config)
```

Phases 2 and 3 can run in parallel after Phase 1.
Phase 4a depends on Phase 1 only (not on 2 or 3).
Phase 4b depends on 4a.
Phase 5 runs last.

---

## Security Considerations

1. **Key never in repo** — `CONTENT_ENCRYPTION_KEY` lives only in `.env` (gitignored) and GitHub Secrets
2. **Decrypted content never on disk** — build-site and admin decrypt in memory only
3. **Authenticated encryption** — AES-GCM prevents tampering with ciphertext
4. **Random IV + salt per encryption** — re-encrypting the same content produces different ciphertext
5. **Graceful degradation** — if key is missing, encrypted articles are skipped (not crashed)
6. **No key logging** — never log the passphrase or derived key
7. **Key rotation** — CLI supports re-encrypting all articles with a new key

---

## Estimated Effort

| Phase | Estimated | Description |
|-------|-----------|-------------|
| Phase 1 | Small | Crypto module + tests (~150 lines code, ~100 lines tests) |
| Phase 2 | Small | Pipeline mods (~50 lines changed, ~80 lines tests) |
| Phase 3 | Small | CLI commands (~200 lines code, ~100 lines tests) |
| Phase 4a | Medium | Backend routes (~250 lines code, ~150 lines tests) |
| Phase 4b | Large | Frontend Editor.js UI (~400 lines HTML/JS) |
| Phase 4c | Small | Manifest editing (~100 lines) |
| Phase 5 | Small | Documentation updates |

---

## Open Questions

1. **Lazy-load Editor.js?** Load CDN scripts only when content tab is activated,
   or include them in `<head>` for faster tab switching? (Recommendation: lazy-load
   to keep initial page load fast)

2. **Offline editing?** Should the editor work without internet (no CDN)?
   Could bundle Editor.js in `static/` as fallback. (Recommendation: CDN-first
   with static fallback for Docker deployments)

3. **Git commit on save?** Should saving an article automatically `git add + commit`?
   (Recommendation: yes, with a descriptive commit message like
   `content: update full_disclosure [encrypted]`)

4. **Manifest auto-update?** When creating a new article in the editor, should it
   auto-add to `manifest.yaml`? (Recommendation: yes, with sensible defaults —
   `min_stage: FULL`, `include_in_nav: true`)
