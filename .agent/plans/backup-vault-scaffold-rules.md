# Backup, Vault, Scaffold & Rules — Feature Plan

## Status: In Planning

---

## 1. Scaffold Article Regeneration

### Problem
Factory reset with `--include-content` wipes **all** articles, including the
essential "How It Works" and "Full Disclosure Statement" articles that the
system ships with. After reset, the site has zero content.

### Solution
Add a `--scaffold` flag (or default behavior) to regenerate these core
articles after a content wipe. The scaffold templates live in code (not in
the user's content directory) so they survive a reset.

### Implementation
- **Template storage**: `src/content/scaffold/` directory with JSON templates:
  - `about.json` — "How It Works"
  - `full_disclosure.json` — "Full Disclosure Statement"
- **CLI**: `reset --full --include-content` gains `--scaffold / --no-scaffold`
  (default: scaffold ON)
- **Factory Reset modal**: New checkbox "Regenerate default articles"
  (default: checked, only visible when "Include content" is checked)
- **Standalone CLI**: `python -m src.main scaffold` to regenerate at any time
- **API**: `POST /api/content/scaffold` for admin UI

### Open Questions
- Should scaffold articles be encrypted by default if CONTENT_ENCRYPTION_KEY
  is set?
- Should we also scaffold the content/manifest.yaml with the default stage
  visibility rules?
- Should the testing_* articles be included as scaffold? (Probably not)

---

## 2. Encrypted .env Vault Export

### Problem
The `.env` file contains all secrets (API keys, tokens, encryption keys).
There's no safe way to back up or transfer these between machines. If the
machine dies, all secrets are lost.

### Solution
An exportable encrypted vault: the `.env` contents encrypted with a
user-provided password, downloadable as a single file.

### Implementation
- **Location in UI**: Under the Export/Import modal, new section:
  "🔐 Secrets Vault"
- **Export flow**:
  1. User clicks "Export Vault"
  2. Modal prompts for a password (+ confirm)
  3. Backend reads `.env`, encrypts with AES-256-GCM using PBKDF2-derived key
  4. Returns downloadable `.vault` file
- **Import flow**:
  1. User uploads `.vault` file
  2. Prompted for password
  3. Backend decrypts, validates, writes to `.env`
  4. Shows diff of what changed
- **File format**: JSON envelope with:
  ```json
  {
    "format": "continuity-vault-v1",
    "created_at": "...",
    "kdf": "pbkdf2-sha256",
    "kdf_iterations": 600000,
    "salt": "hex...",
    "nonce": "hex...",
    "tag": "hex...",
    "ciphertext": "hex..."
  }
  ```
- **Backend**: `src/admin/routes_vault.py` or extend `routes_backup.py`
- **CLI**: `python -m src.main vault-export --password` /
  `python -m src.main vault-import file.vault --password`

### Security Considerations
- Password strength indicator in the UI
- Minimum password length enforcement
- Rate limiting on vault import (prevent brute force)
- Clear warning: "This file contains ALL your secrets"
- The vault file should be `.gitignore`d

---

## 3. Engine Rules — Modal & Backup Integration

### Context
The engine escalation rules (state transitions, timing, actions) are the
core logic of the deadman switch. Currently they're hardcoded or in config
files. A future modal will let users edit these rules from the admin UI.

### When the rules modal is built:
- Rules config needs to be included in backup/export archives
- Factory reset should optionally reset rules to defaults
- The rules storage format (YAML file, JSON, etc.) determines
  how backup/merge handles them

### Not in scope here — this is tracked separately.

---

## 4. Sync After Factory Reset — Gap Analysis

### Current Flow (FIXED)
1. Factory reset → wipes state/audit/content, creates fresh files
2. If `isolated`: sets `MIRROR_ENABLED=false` in `.env` → mirror
   stays independent, no sync reaches it ever again until manually
   re-enabled
3. Sync → `git pull --ff-only` (fails) → `--abort` →
   `git pull -X ours` (local wins) → `git push` (or
   `--force-with-lease` fallback) → `mirror-sync` background
4. Mirror-sync: `push_all_mirrors(force=True)` → force-pushes
   to mirror (only if MIRROR_ENABLED=true, i.e. leader mode)

### What works ✅
- `leader` (default): Reset propagates via force-push to mirrors
- `isolated` (opt-in): MIRROR_ENABLED set to false — truly blocks
  ALL future syncs until manually re-enabled
- Pull conflicts auto-resolve with `-X ours` (local wins)
- Push failures auto-retry with `--force-with-lease`

---

## Priority Order
1. ~~Sync gap fix~~ ✅ Done (force-push fallback)
2. Scaffold articles (quick win, high value)
3. Encrypted vault (medium effort, high value for disaster recovery)
4. Rules integration (blocked on rules modal implementation)
