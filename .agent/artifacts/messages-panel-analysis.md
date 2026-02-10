# Messages Panel — Architecture Analysis

## Current State (2026-02-09)

### What's Done ✅

1. **Backend API** (`routes_messages.py`)
   - `/list` — lists all messages from policy plan, cross-referenced with template files on disk
   - `/templates` — lists all template files on disk (the template browser)
   - `/<name>` GET — loads a template's content
   - `/save` POST — saves template content + updates plan action
   - `/<name>` DELETE — removes template file + plan action
   - `/preview` POST — **real adapter-specific preview**:
     - Email: full styled HTML matching `ResendEmailAdapter._build_styled_email()` (stage themes, urgency bar, footer)
     - SMS: plain text with segment counting (160c/segment)
     - X: char counting with 280-char limit warning
     - Reddit: title/body split
   - `/recipients` GET/POST — manages subscriber/custodian email lists in `state/current.json`
   - `/variables` — lists available template variables

2. **Frontend** (`_messages.html` + `_tab_content.html`)
   - Split-pane editor: content left, **live preview right**
   - Email preview renders in an `<iframe>` showing the exact styled HTML the recipient sees
   - SMS preview in a phone-style bubble with char/segment counter
   - X preview in a tweet card with 280-char counter
   - Reddit preview with title/body split
   - Template picker dropdown populated from disk scan
   - Template name input for new templates
   - Stage / Adapter / Audience dropdowns
   - Variable insertion buttons
   - Debounced live preview (300ms after typing)
   - Recipient management (add/remove subscriber and custodian emails)

3. **Backend Routing Changes**
   - `ResendEmailAdapter` routes to recipients based on `action.channel`:
     - `operator` → `routing.operator_email`
     - `custodians` → `routing.custodian_emails` (list)
     - `subscribers` → `routing.subscriber_emails` (list)
   - `subscriber_emails` field added to `Routing` model + `ExecutionContext.to_payload_dict()`

4. **Adapters**: Email / SMS / X / Reddit (article_publish removed — articles have own tab)

---

## Integration Gap: Scaffold / Factory Reset / Backup-Restore

### The Problem

Templates live in `templates/` which is **git-tracked scaffold content**. The current admin
editor writes directly to those files. This creates three conflicts:

| Scenario | Problem |
|---|---|
| **Factory Reset** (`reset --full`) | Resets repo to defaults. User-customized templates are lost unless backed up. Currently the reset command wipes articles/media but does NOT touch `templates/` — so custom templates survive a reset, but the policy `default.yaml` is reset, orphaning template references. |
| **Backup/Restore** | `create_backup_archive()` includes `policy/` (optionally) but does **not** include `templates/`. Custom templates are not captured. |
| **Export/Import** | `import_from_archive()` handles articles and media only. No template handling. |

### How Other Content Solves This

| Content Type | Storage | Scaffold | Backup | Notes |
|---|---|---|---|---|
| **Articles** | `content/articles/*.json` | `scaffold.py` regenerates defaults | Backed up via `--include-articles` | Separate from site templates |
| **Media** | `content/media/*.enc` | N/A (no defaults) | Backed up via `--include-media` | Encrypted at rest |
| **Policy** | `policy/plans/default.yaml` | Git-tracked scaffold | Backed up via `include_policy=True` | Always restored on factory reset |
| **Templates** | `templates/{operator,custodians,public}/*.md` | ⚠️ **Git-tracked, no separate layer** | ⚠️ **Not included in backup** | ← The gap |

### Proposed Solution

**Option A: Keep templates in `templates/` but add backup coverage** (Minimal change)
- Add `include_templates=True` to `create_backup_archive()` — stores `templates/**/*.md|.txt`
- On factory reset with `--include-content`, use `git checkout -- templates/` to restore scaffold defaults
- Simple, consistent with how `policy/` is already handled

**Option B: Mirror the articles pattern — separate scaffold from user edits**
- Scaffold templates stay in `templates/` (git-tracked, read-only reference)
- User edits go to `content/templates/` (same as `content/articles/`)
- Template resolver checks `content/templates/` first, falls back to `templates/`
- Backup includes `content/templates/`
- Factory reset wipes `content/templates/`, scaffold templates remain
- More complex but cleaner separation of concerns

**Recommended: Option A first**, then evaluate if B is needed as complexity grows.

---

## Future Extensions (Parked)

### Template Encryption
- Same Fernet flow as media: `.md` → `.md.enc` at rest
- Decrypt on edit/preview in admin, on send in adapter
- Priority: **later-stage templates** (PRE_RELEASE, PARTIAL, FULL) contain sensitive disclosure content
- No compression needed (tiny text files)
- Infrastructure already exists in `content/crypto.py`

### Media Insertion in Messages
- Reuse vault picker modal to insert media references into email templates
- Media URLs resolv at send time from `content/media/manifest.json`
- Useful for embedding images in styled emails

### Template Versioning
- Track template changes in audit log entries
- Could use git diff or a simple version counter in the template file header

---

## File Inventory

### Backend
- `src/admin/routes_messages.py` — API endpoints
- `src/admin/server.py` — blueprint registration (line 30, 69)
- `src/adapters/email_resend.py` — email routing + styled HTML (the source of truth for preview)
- `src/models/state.py` — `Routing.subscriber_emails` field
- `src/adapters/base.py` — `subscriber_emails` in payload dict
- `src/policy/models.py` — `ActionDefinition` model
- `src/templates/resolver.py` — template file resolution logic

### Frontend
- `src/admin/templates/scripts/_messages.html` — Messages panel JavaScript
- `src/admin/templates/partials/_tab_content.html` — Messages panel HTML (lines 372-535)
- `src/admin/templates/scripts/_media.html` — `contentSwitchMode()` updated for messages mode
- `src/admin/templates/index.html` — `_messages.html` include (line 35)

### Templates on Disk (Scaffold)
```
templates/
├── operator/
│   ├── reminder_basic.md       ← REMIND_1 email
│   ├── reminder_strong.md      ← REMIND_2 email
│   └── reminder_sms.txt        ← SMS (both stages)
├── custodians/
│   └── pre_release_notice.md   ← PRE_RELEASE email to custodians
├── public/
│   ├── partial_notice.md       ← PARTIAL public notice
│   └── full_release.md         ← FULL public disclosure
└── articles/
    └── full_article.md         ← FULL article (used by article_publish)
```

### Policy Plan Actions (default.yaml)
Each message template corresponds to an action in the plan:
- `stage` → which escalation stage triggers it
- `adapter` → email / sms / x / reddit
- `channel` → operator / custodians / subscribers / public
- `template` → name matches a file in `templates/{channel}/`
