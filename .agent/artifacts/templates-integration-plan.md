# Templates Integration — Backup / Restore / Factory Reset

## Status: ✅ IMPLEMENTED

All 10 steps completed. Templates are now a first-class content type.

---

## Changes Made

### Step 1 ✅ — `src/content/template_scaffold.py` (NEW)
- 7 default templates hardcoded as Python strings
- `generate_template_scaffold(root, encrypt=True, overwrite=False)` 
- Supports encryption at rest (same Fernet pattern as articles)
- Checks for both `.md` and `.md.enc` on overwrite detection

### Step 2 ✅ — `src/cli/backup.py` → `create_backup_archive()`
- Added `include_templates: bool = False` parameter
- Scans `templates/` for `.md`/`.txt`/`.enc` files (excludes `html/`/`css/` dirs)
- Added `content_templates` to manifest includes
- Added `template_count` to manifest stats

### Step 3 ✅ — `src/cli/backup.py` → `restore_from_archive()`
- `templates/` prefix added to `should_restore` block
- Restores when `restore_content=True`

### Step 4 ✅ — `src/cli/backup.py` → `import_from_archive()`
- Collects `templates/` files from archive
- Additive import: skips existing, writes new
- Updated docstring and import guard to include templates

### Step 5 ✅ — `src/cli/core.py` → `reset()`
- Confirmation prompt mentions templates
- Pre-reset backup includes templates when `include_content=True`
- Content wipe deletes `.md`/`.txt`/`.enc` from `templates/` (excludes html/css)
- Scaffold regeneration calls `generate_template_scaffold()` alongside `generate_scaffold()`
- Help texts and docstring updated

### Step 6 ✅ — `src/admin/routes_backup.py`
- `api_export()`: passes `include_templates` to `create_backup_archive()`
- Import guard: accepts archives with `content_templates`

### Step 7 ✅ — `src/admin/routes_content.py` → `api_content_stats()`
- Returns `template_count` and `template_files` (relative paths)
- Scans `templates/` with same exclusion pattern

### Step 8 ✅ — `src/admin/templates/modals/_backup.html`
- Added "✉️ Message templates" checkbox with info label

### Step 9 ✅ — `src/admin/templates/scripts/modals/_backup.js.html`
- Resets checkbox on modal open
- Shows template count from stats API
- Sends `include_templates` in export request
- Shows template count in backup list scope
- Shows template count in import preview
- Import guard accepts template-only archives

### Step 10 ✅ — Factory Reset Modal
- `_factory_reset.html`: scaffold checkbox says "articles and templates"
- `_factory_reset.js.html`: shows template count in stats, confirmation mentions templates

---

## Files NOT Changed (work automatically)
- `routes_core.py` → `api_factory_reset()` — passes `include_content`/`scaffold` to CLI
- `routes_backup.py` → `api_restore()` — passes `restore_content` which now covers templates
- `routes_backup.py` → `api_import()` — calls `import_from_archive()` which now handles templates

---

## CLI Commands Updated
- `backup-export --include-templates` — new flag
- `backup-import` — accepts archives with templates, shows template count
- `reset --full --include-content` — wipes + scaffolds templates
