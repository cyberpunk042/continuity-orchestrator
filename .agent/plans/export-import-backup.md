---
description: Export/Import system + backup restructure for factory reset
status: PLANNING
created: 2026-02-08
---

# Export / Import / Backup Restructure

## The Problem

### Current backup state
- `backups/` contains 19 flat state JSON files — **all tracked in git**
- No audit backups exist on disk (path in code but never triggered)
- No content backup mechanism
- No import/restore capability
- No archive format — just loose file copies
- No metadata about what a backup contains

### What's needed
A unified **archive-based** backup system that serves three use cases:

| Use case | Trigger | Contents |
|----------|---------|----------|
| **Factory reset safety net** | Auto, when "Backup" is checked in factory reset modal | State + audit (+ content if content reset is checked) |
| **Manual export** | User clicks "Export" button | User chooses scope |
| **Import / restore** | User uploads an archive or selects a local backup | Selectively restores files |

All three produce/consume the **same archive format**.

---

## Archive Format

```
backup_20260208T141300.tar.gz
├── backup_manifest.json      ← archive metadata
├── state/
│   └── current.json           ← state snapshot
├── audit/
│   └── ledger.ndjson          ← audit log
├── content/                   ← optional
│   ├── manifest.yaml          ← content manifest (stage defs + article registry)
│   └── articles/
│       ├── about.json         ← plaintext article (EditorJS blocks)
│       ├── testing.json       ← encrypted article (AES-256-GCM envelope)
│       └── ...
└── media/                     ← optional, if user opted in
    ├── manifest.json          ← media registry
    ├── img_001.enc            ← encrypted media file
    └── ...
```

### `backup_manifest.json`

```json
{
    "format_version": 1,
    "created_at": "2026-02-08T14:13:00Z",
    "project": "my-deadman",
    "trigger": "manual_export",
    "includes": {
        "state": true,
        "audit": true,
        "content_articles": true,
        "content_media": true
    },
    "stats": {
        "article_count": 7,
        "articles_encrypted": 5,
        "articles_plaintext": 2,
        "media_count": 4,
        "media_bytes": 957543
    },
    "encryption_notice": "This archive contains encrypted content. Articles marked encrypted=true and all media .enc files require the original CONTENT_ENCRYPTION_KEY to be usable. This key is NOT included in the archive — you must back it up separately using a secure method (vault, encrypted zip, etc.)."
}
```

---

## Content Encryption Handling

### Two article formats exist on disk

| File | `encrypted` field | Body format |
|------|-------------------|-------------|
| `about.json` | absent/false | EditorJS blocks (plaintext) |
| `testing.json` | `true` | AES-256-GCM envelope (salt, iv, tag, ciphertext) |

### Media files
- Always `.enc` — binary COVAULT encrypted envelope
- Always require `CONTENT_ENCRYPTION_KEY` to decrypt

### Export options for content

The export modal shows:

```
📝 Include content
  ├── [✓] Articles (7 files — 2 plaintext, 5 encrypted)
  └── [✓] Media (4 files, 935 KB — all encrypted)

⚠️ Encrypted content notice:
   Encrypted articles and all media files (.enc) require your
   CONTENT_ENCRYPTION_KEY to be readable after import.

   This key is NOT included in the export.
   Back it up separately using a secure method:
   • Password manager or vault
   • Encrypted archive (RAR/7z with password)
   • Air-gapped storage

   ❌ Never export your .env file or encryption keys
      in the same archive as your content.
```

There is **no toggle to decrypt on export** — that would put plaintext evidence
on disk in an unprotected archive. Articles are exported in their current state
(encrypted or plaintext). Media is always exported as `.enc`.

The user's choice is simply: include content or not.

---

## UI Design

### Debugging tab — new button

```
┌────────────────────────────────────────────┐
│ 🔧 State Controls                          │
│                                             │
│  [🔄 Reset Timer (keep secrets, OK + 48h)] │
│  [🗑️ Factory Reset (fresh state + audit) ] │
│  [📦 Export / Import                      ] │
└────────────────────────────────────────────┘
```

### Export / Import Modal

```
┌─────────────────────────────────────────────┐
│  📦 Export / Import                          │
│                                              │
│  ── Export ──────────────────────────────     │
│  Create a portable snapshot of your system.  │
│                                              │
│  [✓] State (current.json)                    │
│  [✓] Audit log (ledger.ndjson)               │
│  [ ] Content articles (N files)              │
│    └ 2 plaintext, 5 encrypted                │
│  [ ] Content media (N files, X KB)           │
│    └ All encrypted (.enc)                    │
│                                              │
│  ⚠️ Encrypted content requires your          │
│  CONTENT_ENCRYPTION_KEY (not included).      │
│  Back it up separately.                      │
│                                              │
│           [📥 Export & Download]              │
│                                              │
│  ── Import ──────────────────────────────    │
│  Restore from a previously exported archive. │
│                                              │
│  [Choose file...]   backup_20260208.tar.gz   │
│  ↳ Contains: state, audit, 7 articles        │
│    Selective restore:                         │
│    [✓] State   [✓] Audit   [✓] Content       │
│                                              │
│  ⚠️ This will overwrite current files.       │
│                                              │
│           [📤 Restore Selected]              │
│                                              │
│  ── Local Backups ───────────────────────    │
│  Previously created backups on this machine. │
│                                              │
│  📁 backup_20260208T141300.tar.gz (12 KB)    │
│     State + Audit | Created 2 hours ago      │
│     [📥 Download] [📤 Restore]               │
│                                              │
│  📁 backup_20260207T034141.tar.gz (48 KB)    │
│     State + Audit + Content | Created 1 day  │
│     [📥 Download] [📤 Restore]               │
│                                              │
│                         [Close]              │
└─────────────────────────────────────────────┘
```

---

## Factory Reset Integration

The factory reset modal's "💾 Backup" checkbox now creates an archive using
the same format. The archive is stored in `backups/` and is available in the
Export/Import modal's "Local Backups" section.

When "Also wipe content" is checked in the factory reset modal, the auto-backup
archive includes content (articles + media) automatically — the user doesn't
have to choose.

---

## `.gitignore` Fix

```gitignore
# Backups — local safety nets, never tracked in git
backups/
```

The 19 existing tracked backup files need to be removed from git index:
```bash
git rm -r --cached backups/
```

---

## File Inventory

### New files
| File | Purpose |
|------|---------|
| `src/cli/backup.py` | CLI commands: `export`, `import` |

### Modified files
| File | Change |
|------|--------|
| `.gitignore` | Add `backups/` |
| `src/main.py` | Register `export` and `import` commands |
| `src/cli/core.py` | Refactor backup in `reset` to use archive format |
| `src/admin/routes_core.py` | API endpoints: export, import, list backups, download |
| `partials/_tab_debugging.html` | Export/Import button + modal HTML |
| `scripts/_wizard.html` | Export/Import JS functions |

### NOT touched
| File | Why |
|------|-----|
| `.env` | Never included in any export. Explicitly warned against. |
| `routes_content.py` | Content stats endpoint already exists |
| `content/` | Read from, but export doesn't modify content |

---

## API Endpoints

### `POST /api/backup/export`
```json
Request:
{
    "include_state": true,
    "include_audit": true,
    "include_articles": false,
    "include_media": false
}

Response:
{
    "success": true,
    "filename": "backup_20260208T141300.tar.gz",
    "size_bytes": 12480,
    "download_url": "/api/backup/download/backup_20260208T141300.tar.gz"
}
```

### `GET /api/backup/download/<filename>`
Returns the `.tar.gz` file as a download.

### `GET /api/backup/list`
```json
Response:
{
    "backups": [
        {
            "filename": "backup_20260208T141300.tar.gz",
            "size_bytes": 12480,
            "created_at": "2026-02-08T14:13:00Z",
            "manifest": { ... }
        }
    ]
}
```

### `POST /api/backup/import`
Multipart form upload of a `.tar.gz` file.
```json
Response (preview):
{
    "success": true,
    "preview": true,
    "manifest": { ... },
    "conflicts": ["state/current.json exists and will be overwritten"]
}
```

### `POST /api/backup/restore`
```json
Request:
{
    "filename": "backup_20260208T141300.tar.gz",
    "restore_state": true,
    "restore_audit": true,
    "restore_content": false
}
Response:
{
    "success": true,
    "restored": ["state/current.json", "audit/ledger.ndjson"]
}
```

---

## Implementation Order

### Step 0: Fix gitignore + untrack existing backups
- Add `backups/` to `.gitignore`
- `git rm -r --cached backups/`

### Step 1: CLI — `src/cli/backup.py`
- `export` command: creates archive in `backups/`
- `import` command: reads archive, validates manifest, restores selected layers

### Step 2: Refactor factory reset backup
- `src/cli/core.py`: replace `shutil.copy` calls with archive creation
- Use same logic as `export` command

### Step 3: API layer
- `src/admin/routes_core.py` (or new `routes_backup.py`): export, download, list, import, restore

### Step 4: UI
- `_tab_debugging.html`: Export/Import button + modal
- `_wizard.html`: JS for export, import, backup list

---

## Security Notes

1. **`.env` is NEVER exported.** The modal explicitly warns the user.
2. **CONTENT_ENCRYPTION_KEY is NEVER included.** The archive manifest includes
   a notice explaining this.
3. **Encrypted articles are exported as-is.** No decryption during export.
4. **Archives are stored locally in `backups/` (gitignored).** They are NOT
   pushed to origin or mirrors.
5. **Import validates the manifest** before any file writes — no arbitrary
   file extraction (path traversal protection).
6. **Download endpoint validates filename** — cannot be used to read arbitrary files.
