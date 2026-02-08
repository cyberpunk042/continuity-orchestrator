# Exploration Plan — Feb 8, 2026

All topics from the exploration session, analyzed and ordered by priority.
Work through sequentially. Each section contains root cause analysis, affected
files, and implementation steps.

---

## 1. 🧪 Fix Failing Tests (47 failed, 25 errors)

### Status: `427 passed, 47 failed, 25 errors, 2 collection errors`

### Root Cause A: Jinja2 `PosixPath` incompatibility (23+ tests)

**Problem**: `SiteGenerator.__init__` passes a `Path` object to `FileSystemLoader()`.
On Python 3.8 + older jinja2, `FileSystemLoader` doesn't accept `Path` — it tries
`list(searchpath)` which fails with `TypeError: 'PosixPath' object is not iterable`.

This **cascades** — every test that instantiates `SiteGenerator` fails, including:
- All 15 tests in `test_site_generator.py`
- All 8 tests in `test_generator_media.py` (because they create a SiteGenerator
  to test `_process_media`)

**Fix**: One-line change in `src/site/generator.py` line 42:
```python
# Before:
loader=FileSystemLoader(self.template_dir / "html"),
# After:
loader=FileSystemLoader(str(self.template_dir / "html")),
```

**Files**: `src/site/generator.py`

### Root Cause B: Environment bleed — `CONTENT_ENCRYPTION_KEY` (8 tests)

**Problem**: Tests that assert `get_encryption_key() is None` fail because the
developer's `.env` file has `CONTENT_ENCRYPTION_KEY` set. The `get_encryption_key()`
function reads `.env` from disk (lines 135-149 in `crypto.py`) as a fallback when
the env var isn't in `os.environ`.

Tests affected:
- `test_content_crypto.py` — TestGetEncryptionKey (3 tests)
- `test_content_crypto.py` — TestLoadArticle::test_load_encrypted_no_key_raises
- `test_content_crypto.py` — TestSaveArticle::test_save_encrypted_no_key_raises
- `test_cli_content.py` — 3 tests (encrypt/decrypt/status no-key)
- `test_content_pipeline.py` — 1 test

**Root cause detail**: `get_encryption_key()` has a `.env` file fallback (lines 134-149
in `crypto.py`). The tests use `mock.patch.dict(os.environ, {}, clear=True)` which
clears os.environ, but the function then reads `../../.env` from disk and finds the
real key there. The tests need to also mock the file fallback.

**Fix approach**: Patch `get_encryption_key` itself to return `None` in the
"no key" tests. This is more robust than trying to mock both os.environ AND
the .env file reader. Specific approach per file:

- `test_content_crypto.py` (3 tests: TestGetEncryptionKey::test_key_not_set,
  test_key_empty_string, test_key_whitespace_only): These test `get_encryption_key()`
  directly, so we can't mock it. Instead, we need to mock the `.env` file path
  to not exist. Use `monkeypatch` to set `src.content.crypto.Path.__file__` won't
  work — better to use `@mock.patch` on `Path.exists` scoped to just the `.env` check.
  **Simplest fix**: mock `Path.read_text` of the `.env` file to return empty or
  use `mock.patch.object` on the env_file Path.
  
  Actually, looking more carefully: these 3 tests use `clear=True` which should
  work, but the `.env` file on disk provides the fallback. The cleanest fix:
  use `tmp_path` as the project root and mock `Path(__file__).resolve().parents[2]`.
  OR: simply add `monkeypatch.delenv(ENV_VAR, raising=False)` AND mock the `.env`
  path to a non-existent file.

- `test_content_crypto.py` (2 tests: TestLoadArticle::test_load_encrypted_no_key_raises,
  TestSaveArticle::test_save_encrypted_no_key_raises): Already use
  `mock.patch.dict(os.environ, {}, clear=True)` — same fix needed.

- `test_cli_content.py` (3 tests: test_shows_key_not_set, test_encrypt_no_key_fails,
  test_decrypt_no_key_fails): These use `_run(..., env={})` which passes empty env
  to CliRunner. But `get_encryption_key()` reads `.env` from disk. Need to mock
  the `.env` path.

- `test_content_pipeline.py` (1 test: test_get_encrypted_article_no_key_raises):
  Same pattern — `clear=True` but `.env` fallback finds the key.

**Files**: `tests/test_content_crypto.py`, `tests/test_cli_content.py`,
`tests/test_content_pipeline.py`, and possibly `src/content/crypto.py` (add a
testable seam for the `.env` file path)

### Root Cause C: Media manifest ID format changed (4 tests)

**Problem**: `MediaManifest.next_id()` was changed from sequential (`img_001`)
to date-based (`img_20260208_adfd`). Tests in `test_media_manifest.py` still
assert the old format.

Tests: `TestIdGeneration` — test_first_id, test_sequential_ids, test_gap_in_sequence,
test_different_prefixes, test_default_prefix

**Fix**: Update test assertions to match the new format pattern (prefix + date + random).
Use regex matching or `startswith()` instead of exact equality.

**Files**: `tests/test_media_manifest.py`

### Root Cause D: Flask not installed — collection errors (2 + 25)

**Problem**: `test_editor_image.py` and `test_media_api.py` import `src.admin.server`
at module level which imports Flask. Flask isn't in the base install dependencies.

`test_routes_content.py` also fails (25 ERRORs) — it imports `src.admin.server`
inside a fixture, but pytest still fails at collection time if the fixture is
referenced by test classes.

**Fix**: Add `pytest.importorskip("flask")` at the TOP of each file (before any
other imports from the admin package). This causes pytest to skip the entire
module gracefully when Flask is not available.

```python
# At the very top, after the docstring
pytest.importorskip("flask")
```

Note: For `test_routes_content.py`, the import is already lazy (inside fixture),
but we still need the guard because the fixture's `from src.admin.server import`
fails when the fixture is instantiated.

**Files**: `tests/test_editor_image.py`, `tests/test_media_api.py`,
`tests/test_routes_content.py`

### Implementation order:
1. Fix Jinja2 Path issue (1 line) — unblocks 23 tests
2. Fix env bleed in crypto tests — unblocks 8 tests
3. Fix media manifest ID assertions — unblocks 4-5 tests
4. Add importorskip for Flask tests — eliminates 27 errors

---

## 2. 🔑 Renewal Token Exposure in Built Site

### Problem

Line 180 of `templates/html/countdown.html`:
```javascript
const TRIGGER_TOKEN = "{{ renewal_trigger_token }}";
```

The raw GitHub PAT is injected verbatim into public HTML source. Anyone can
View Source → extract the token → call the GitHub API to trigger arbitrary
workflow dispatches on the repo.

The token is a fine-grained PAT scoped to workflow dispatch only. It can't
read code or push commits. But it can:
- Trigger unlimited renewals (DoS the deadline system)
- Trigger the release workflow if RELEASE_SECRET is guessed

### Mitigation levels

**Level 1 — Base64 obfuscation** (minimum viable):
- Template: `const _T = "{{ renewal_trigger_token | b64encode }}";`
- JS: `const TRIGGER_TOKEN = atob(_T);`
- Stops casual View Source inspection. Trivially reversible but raises the bar.

**Level 2 — Split + reassemble** (moderate):
- Template splits token into 3 chunks, JS reassembles at call time
- Harder to grep for in automated scans

**Level 3 — Cloudflare Worker proxy** (proper):
- Token never reaches the client
- Worker validates a HMAC-signed request from the site
- Requires Cloudflare account (aligns with Topic 4: cloudflared sidecar)

### Recommended: Level 1 for now (quick win), Level 3 later when cloudflared is set up.

### Files:
- `src/site/generator.py` — add a Jinja2 filter for base64 encoding
- `templates/html/countdown.html` — encode the token output, decode in JS

---

## 3. 🔐 Vault Password Detection / Auto-Lock Suggestion

### Problem

When the server restarts, `_session_passphrase` is `None`. If the vault is
unlocked (`.env` exists), auto-lock can't fire because there's no passphrase
to encrypt with. The user has no indication that this is the case.

### Current state:
- `/api/vault/status` returns `has_passphrase: true/false` ✅
- UI does NOT surface this state to the user ❌
- No way to register the passphrase without doing a full lock/unlock cycle ❌

### Design:

**UI prompt** (non-blocking banner in admin panel):
When `locked=false` AND `has_passphrase=false`:
- Show a soft banner: "🔐 Auto-lock unavailable — register your vault password"
- Click opens a minimal modal (reuses vault modal styling):
  - Password field
  - "Register" button → calls `/api/vault/register-passphrase`
  - "Not now" (dismiss for this page load — sessionStorage)
  - "Don't ask again" (dismiss permanently — localStorage)

**Backend**:
- New endpoint: `POST /api/vault/register-passphrase`
  - Accepts `{ passphrase: "..." }`
  - Verifies the passphrase is correct by attempting a trial decrypt of
    `.env.vault` (if it exists) or by encrypting + decrypting a test string
  - On success: sets `_session_passphrase` + starts auto-lock timer
  - On failure: returns 401

**Architecture compliance** (per before-any-change.md):
- This is admin-panel-only — no pipeline/cron impact
- No new env vars needed
- No GitHub secrets/vars needed
- UI function calls: need to verify existing function names
- Server pattern: this one is direct vault logic, not CLI subprocess — matches
  existing vault routes pattern (routes_vault.py imports vault.py directly)

### Files:
- `src/admin/vault.py` — add `register_passphrase()` function
- `src/admin/routes_vault.py` — add `/api/vault/register-passphrase` endpoint
- `src/admin/templates/partials/_tab_debugging.html` — banner HTML (or a global
  banner position)
- `src/admin/templates/scripts/_wizard.html` or `_globals.html` — JS for banner
  logic + dismiss persistence

---

## 4. ☁️ Cloudflared Sidecar in Docker Compose

### Current state

`docker-compose.yml` has profiles: `git-sync`, `tools`. No tunnel/cloudflare support.
The nginx service exposes port 8080 locally.

### Design

Add a `cloudflared` service under a new `tunnel` profile:

```yaml
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: continuity-tunnel
    restart: unless-stopped
    profiles:
      - tunnel
    depends_on:
      nginx:
        condition: service_started
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN:-}
    command: tunnel run
    networks:
      - continuity-net
```

### Usage:
```bash
# Git-sync + tunnel:
docker compose --profile git-sync --profile tunnel up -d
```

### Requirements:
- User creates a Cloudflare Tunnel in the dashboard → gets a tunnel token
- Token goes in `.env` as `CLOUDFLARE_TUNNEL_TOKEN`
- Tunnel points to `http://nginx:80` (internal Docker network)
- No ports exposed on host — everything goes through the tunnel

### New env var:
- `CLOUDFLARE_TUNNEL_TOKEN` — add to `LOCAL_ONLY` tier (never syncs to GitHub)
- Add to `system_status.py` guidance
- Add to wizard as optional field

### Files:
- `docker-compose.yml` — add cloudflared service
- `src/config/system_status.py` — add var guidance
- Optionally: `src/admin/templates/scripts/_wizard.html` — add tunnel token field

---

## 5. 🖼️ Media Viewer Support

### Current state

Media upload accepts **any file type** — images, videos, PDFs, audio, text, etc.
MIME prefix determines the ID prefix:
- `image/*` → `img_*`
- `video/*` → `vid_*`
- `audio/*` → `aud_*`
- `application/pdf` → `doc_*`
- Everything else → `media_*`

However the **site generator** only outputs media as raw files in `public/media/`.
The article template uses `<img>` tags for all media (via EditorJS Image tool).
There's no `<video>`, `<audio>`, `<embed>` rendering.

### What works today:
- ✅ Images (jpg, png, gif, webp, svg) — display correctly
- ❌ Videos — stored but rendered as broken `<img>` tags
- ❌ PDFs — stored but no embed/viewer
- ❌ Audio — stored but no player
- ❌ Text/other — stored, no rendering

### What to add (later — this is feature work, not a fix):
1. **EditorJS renderer** (`src/site/editorjs.py`): detect MIME type and emit
   `<video>`, `<embed>`, `<audio>` tags instead of `<img>` for non-image media
2. **Admin preview**: media preview endpoint already serves correct MIME type,
   but the editor UI only renders images
3. **Site templates**: add CSS for video/PDF containers

### Priority: Low — this is a feature gap, not a bug. Media upload works correctly
for images which is the primary use case. Video/PDF can be added when needed.

---

## 6. ✅ Pipeline Secrets Sync (VERIFIED — NO ACTION NEEDED)

Cross-reference confirmed:
- `SYNCABLE_SECRETS` (github_sync.py) ↔ `cron.yml` mirror-sync env: **in sync**
- `RENAMED_SECRETS` (MIRROR_1_RENEWAL_TRIGGER_TOKEN) ↔ `cron.yml` line 184: **in sync**
- `SYNCABLE_VARS` ↔ `cron.yml` vars: references: **in sync**
- `deploy-site.yml` has RENEWAL_TRIGGER_TOKEN + CONTENT_ENCRYPTION_KEY: **correct**
- `renew.yml` has RENEWAL_SECRET + RELEASE_SECRET + RENEWAL_TRIGGER_TOKEN: **correct**
- `test.yml` — no secrets needed: **correct**

**CONTENT_ENCRYPTION_KEY** is deliberately NOT synced to mirrors — this is by design.
The mirror can only serve content that's committed in plaintext. If the mirror needs
to independently decrypt content, it would need its own key set manually.

---

## Execution Order

| Step | Topic | Scope | Est. Effort |
|------|-------|-------|-------------|
| 1a | Fix Jinja2 Path → str | 1 line in generator.py | 2 min |
| 1b | Fix env bleed in crypto tests | ~8 tests need mock | 15 min |
| 1c | Fix media manifest ID tests | ~5 test assertions | 10 min |
| 1d | Add importorskip for Flask tests | 3 files, 1 line each | 5 min |
| 1e | Verify: run full test suite green | — | 2 min |
| 2 | Renewal token base64 obfuscation | generator.py + countdown.html | 10 min |
| 3 | Vault password registration prompt | vault.py + routes + UI | 45 min |
| 4 | Cloudflared sidecar | docker-compose.yml + system_status | 15 min |
| 5 | Media viewer support (later) | editorjs.py + templates | deferred |
| 6 | Pipeline verification | done | 0 min |
