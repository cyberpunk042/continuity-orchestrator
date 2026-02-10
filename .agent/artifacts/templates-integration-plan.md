# Templates Integration — Backup / Restore / Factory Reset

## Goal

Make message templates a first-class content type across the entire lifecycle:
backup, restore, import, factory reset, and scaffold regeneration.
Follow the exact patterns already established for articles.

---

## File Map

| Step | File | Action |
|------|------|--------|
| 1 | `src/content/template_scaffold.py` | **CREATE** — hardcoded defaults + `generate_template_scaffold()` |
| 2 | `src/cli/backup.py` → `create_backup_archive()` | **EDIT** — add `include_templates` param |
| 3 | `src/cli/backup.py` → `restore_from_archive()` | **EDIT** — handle `templates/` prefix |
| 4 | `src/cli/backup.py` → `import_from_archive()` | **EDIT** — additive template import |
| 5 | `src/cli/core.py` → `reset()` | **EDIT** — wipe + scaffold templates |
| 6 | `src/admin/routes_backup.py` → `api_export()` | **EDIT** — pass `include_templates` |
| 7 | `src/admin/routes_content.py` → `api_content_stats()` | **EDIT** — add template stats |
| 8 | `src/admin/templates/modals/_backup.html` | **EDIT** — templates checkbox |
| 9 | `src/admin/templates/scripts/modals/_backup.js.html` | **EDIT** — send flag + show stats |
| 10 | `src/admin/templates/modals/_factory_reset.html` | **EDIT** — show template stats |
| 11 | `src/admin/templates/scripts/modals/_factory_reset.js.html` | **EDIT** — display template count |

---

## Step 1: Template Scaffold — `src/content/template_scaffold.py` (NEW FILE)

Mirror `src/content/scaffold.py` exactly.

```python
SCAFFOLD_TEMPLATES = {
    "operator/reminder_basic.md": "...",      # REMIND_1 email
    "operator/reminder_strong.md": "...",     # REMIND_2 email  
    "operator/reminder_sms.txt": "...",       # REMIND_2 SMS
    "custodians/pre_release_notice.md": "...",# PRE_RELEASE custodian email
    "public/partial_notice.md": "...",        # PARTIAL public notice
    "public/full_release.md": "...",          # FULL public disclosure
    "articles/full_article.md": "...",        # FULL article publish
}

def generate_template_scaffold(root: Path, *, overwrite: bool = False) -> dict:
    """Regenerate default message templates in templates/.
    
    Args:
        root: Project root directory.
        overwrite: If True, overwrite existing templates with same path.
    
    Returns:
        {"created": [...], "skipped": [...]}
    """
    templates_dir = root / "templates"
    created, skipped = [], []
    
    for rel_path, content in SCAFFOLD_TEMPLATES.items():
        dest = templates_dir / rel_path
        if dest.exists() and not overwrite:
            skipped.append(rel_path)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        created.append(rel_path)
    
    return {"created": created, "skipped": skipped}
```

Each template's content is the full file content hardcoded as a Python string.
On factory reset, this function is called to regenerate all defaults.

**Source content**: Read from the 7 files currently in `templates/` on disk.

---

## Step 2: Backup Archive — `cli/backup.py` → `create_backup_archive()`

Add parameter: `include_templates: bool = False`

In the archive creation block (after the Policy section ~line 218-224):

```python
# Templates
if include_templates:
    templates_dir = root / "templates"
    excluded = {"html", "css"}
    if templates_dir.exists():
        for f in sorted(templates_dir.rglob("*")):
            if f.is_file() and f.suffix in {".md", ".txt"} and not any(
                p.name in excluded for p in f.relative_to(templates_dir).parents
            ):
                arcname = f"templates/{f.relative_to(templates_dir)}"
                tar.add(str(f), arcname=arcname)
```

Update manifest:
- `includes.content_templates: bool` 
- `stats.template_count: int` (count of template files)

---

## Step 3: Restore — `cli/backup.py` → `restore_from_archive()`

In the `should_restore` block (~line 289-296), add:

```python
elif member.name.startswith("templates/") and restore_content:
    should_restore = True
```

Templates restore with content. No separate flag needed — they're part of content.

---

## Step 4: Import — `cli/backup.py` → `import_from_archive()`

After the articles and media import sections, add template handling:

```python
# Collect template files from archive
archive_templates = {}
for member in tar.getmembers():
    if member.name.startswith("templates/") and member.isfile():
        archive_templates[member.name] = member

# Import templates that don't exist locally
for name, member in sorted(archive_templates.items()):
    dest = root / name  # e.g. root / "templates/operator/reminder_basic.md"
    if dest.exists():
        skipped.append(f"template:{name} (already exists)")
    else:
        src = tar.extractfile(member)
        if src:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read())
            imported.append(f"template:{name}")
```

Also update the import guard check (~line 253) to allow archives with templates:
```python
if not includes.get("content_articles") and not includes.get("content_media") and not includes.get("content_templates"):
```

---

## Step 5: Factory Reset — `cli/core.py` → `reset()`

In the `--include-content` block (after media wipe, ~line 197-211), add template wipe:

```python
# Wipe user templates
templates_dir = root / "templates"
deleted_templates = 0
excluded_dirs = {"html", "css"}
if templates_dir.exists():
    for f in templates_dir.rglob("*"):
        if f.is_file() and f.suffix in {".md", ".txt"} and not any(
            p.name in excluded_dirs for p in f.relative_to(templates_dir).parents
        ):
            f.unlink()
            deleted_templates += 1
click.echo(f"    Deleted {deleted_templates} template(s)")
```

In the scaffold section (~line 229-237), add template scaffold:

```python
if scaffold:
    # Existing article scaffold
    from ..content.scaffold import generate_scaffold
    result = generate_scaffold(root)
    ...
    
    # Template scaffold
    from ..content.template_scaffold import generate_template_scaffold
    tpl_result = generate_template_scaffold(root)
    tpl_created = tpl_result["created"]
    if tpl_created:
        click.echo(f"    ✉️ Templates: regenerated {len(tpl_created)} default(s)")
    else:
        click.echo("    ✉️ Templates: no templates to create")
```

Update the confirmation prompt (~line 68-77) to mention templates:
```python
if include_content:
    click.echo("  - Delete all articles, media, and templates")
```

Update `create_backup_archive()` call (~line 88-97) to include templates:
```python
archive_path, manifest = create_backup_archive(
    root,
    ...
    include_templates=include_content,
    ...
)
```

---

## Step 6: Admin Export API — `routes_backup.py` → `api_export()`

One-line addition at line 60:

```python
include_templates=data.get("include_templates", False),
```

---

## Step 7: Content Stats — `routes_content.py` → `api_content_stats()`

Add template counting after the existing article/media stats:

```python
# Template stats
templates_dir = project_root / "templates"
template_files = []
excluded_dirs = {"html", "css"}
if templates_dir.exists():
    for f in templates_dir.rglob("*"):
        if f.is_file() and f.suffix in {".md", ".txt"} and not any(
            p.name in excluded_dirs for p in f.relative_to(templates_dir).parents
        ):
            template_files.append(str(f.relative_to(templates_dir)))
```

Add to response: `"template_count": len(template_files)`, `"template_files": sorted(template_files)`

---

## Step 8: Backup Modal HTML — `_backup.html`

After the Policy checkbox (line 37), add:

```html
<label style="display: flex; align-items: flex-start; gap: 0.6rem; cursor: pointer; margin-bottom: 0.5rem; font-size: 0.88rem;">
    <input type="checkbox" id="bk-export-templates"
           style="width: 17px; height: 17px; margin-top: 2px; accent-color: var(--accent);">
    ✉️ Message templates
</label>
<div id="bk-export-templates-info" style="margin-left: 2rem; font-size: 0.8rem; color: var(--text-dim); margin-bottom: 0.5rem;"></div>
```

---

## Step 9: Backup Modal JS — `_backup.js.html`

In `openBackupModal()` — reset the checkbox:
```javascript
document.getElementById('bk-export-templates').checked = false;
```

In the stats fetch — show template count:
```javascript
document.getElementById('bk-export-templates-info').innerHTML =
    `${s.template_count} file(s) — ${s.template_files.join(', ') || 'none'}`;
```

In `doExport()` — read and send the flag:
```javascript
const includeTemplates = document.getElementById('bk-export-templates').checked;
// Add to the if-nothing-selected check
// Add to fetch body: include_templates: includeTemplates
```

In `loadBackupList()` — show template count in scope:
```javascript
if (inc.content_templates) parts.push(`${stats.template_count} templates`);
```

In `previewUpload()` — show template count in preview:
```javascript
if (inc.content_templates) parts.push(`${stats.template_count} templates`);
```

In `doImport()` — update the import guard to accept archives with templates:
```javascript
if (inc.content_articles || inc.content_media || inc.content_templates) {
```

---

## Step 10: Factory Reset Modal — `_factory_reset.html` + JS

In `_factory_reset.js.html` → `openFactoryResetModal()` stats display, add:
```javascript
• ${s.template_count} message template(s)
```

In `_factory_reset.html` → scaffold checkbox label, update to:
```
📄 Regenerate default articles and message templates
```

In `executeFactoryReset()` confirmation prompt:
```javascript
if (includeContent) parts.push('• Delete ALL articles, media, and templates');
```

---

## Execution Order

1. **Step 1** first — create the scaffold file (no dependencies)
2. **Step 2-4** — backup.py changes (all in one edit session)
3. **Step 5** — factory reset CLI changes
4. **Step 6-7** — admin API changes
5. **Step 8-11** — UI changes (modals)
6. **Test**: factory reset via UI, verify templates wiped + regenerated
7. **Test**: export with templates, verify archive contains them
8. **Test**: restore from archive, verify templates restored
9. **Test**: import, verify additive behavior (skip existing)

---

## Files NOT Changed

- `routes_core.py` → `api_factory_reset()` — already passes `include_content` and `scaffold` to CLI; works automatically once CLI is updated
- `routes_backup.py` → `api_restore()` — already passes `restore_content`; works automatically once `restore_from_archive()` handles `templates/`
- `routes_backup.py` → `api_import()` — already calls `import_from_archive()`; works automatically once import handles templates
