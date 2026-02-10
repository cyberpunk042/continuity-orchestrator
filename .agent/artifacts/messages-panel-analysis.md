---
title: Messages Panel — Definitive Analysis & Implementation Plan
created: 2026-02-09T19:23:00-05:00
status: AWAITING_APPROVAL
---

# Messages Panel — Definitive Analysis & Implementation Plan

---

## 1. What This Feature Is

A messaging system inside the admin UI where the user **creates, edits, and
manages** the notifications their system sends at each escalation stage.

The user decides:
- **What stage** triggers the message (REMIND_1, REMIND_2, PRE_RELEASE, PARTIAL, FULL)
- **What adapter** delivers it (email, sms, x, reddit)
- **Who receives it** (operator, subscribers, custodians, public)
- **What content** it contains (written by the user, adapter-appropriate)

There can be **any number of messages per stage**. Example:

```
REMIND_1:
  ├─ 📧 Email → operator     "Your deadline is approaching..."
  ├─ 📧 Email → subscribers  "The operator hasn't renewed yet..."
  └─ 📱 SMS  → operator      "Deadline in 120min. Renew now."

REMIND_2:
  ├─ 📧 Email → operator     "URGENT — Renewal required immediately"
  ├─ 📧 Email → subscribers  "Final warning: escalation imminent"
  └─ 📱 SMS  → operator      "⚠️ URGENT: Renew now."

PRE_RELEASE:
  └─ 📧 Email → custodians   "Pre-release notice..."

PARTIAL:
  ├─ 🐦 X    → public        "A continuity process has entered..."
  └─ 🤖 Reddit → public      "A continuity process has entered..."

FULL:
  ├─ 🐦 X    → public        "Full execution..."
  ├─ 🤖 Reddit → public      "Full execution..."
  └─ 📰 Article → public     "Continuity Execution Summary..."
```

---

## 2. How It Connects to What Exists

### 2a. Template Files (`templates/`)

Each message maps to a **template file** on disk:

```
templates/
├── operator/
│   ├── reminder_basic.md          ← REMIND_1 email to operator
│   ├── reminder_strong.md         ← REMIND_2 email to operator
│   └── reminder_sms.txt           ← REMIND_2 sms to operator
├── custodians/
│   └── pre_release_notice.md      ← PRE_RELEASE email to custodians
├── public/
│   ├── partial_notice.md          ← PARTIAL x+reddit to public
│   └── full_release.md            ← FULL x+reddit to public
└── articles/
    └── full_article.md            ← FULL article to public
```

When the user creates a new message → a new template file is created.
When the user edits a message → the template file is updated.
When the user deletes a message → the template file is removed.

### 2b. Policy Plan (`policy/plans/default.yaml`)

Each message also maps to an **action entry** in the policy plan:

```yaml
REMIND_1:
  actions:
    - id: remind_email_primary           # ← auto-generated unique ID
      adapter: email                     # ← user chose "email"
      channel: operator                  # ← user chose "operator"
      template: reminder_basic           # ← links to the template file
      constraints:
        no_links: true
        no_entrypoint_reference: true
```

When the user saves a message → the corresponding action in `default.yaml`
is created/updated. When they delete → the action is removed.

### 2c. Adapter Routing (`src/adapters/email_resend.py`)

Currently broken: the email adapter always sends to `operator_email` (line 90),
ignoring the `channel` field.

**Fix required:**

```python
def execute(self, context):
    channel = context.action.channel
    if channel == "custodians":
        recipients = context.routing.custodian_emails
    elif channel == "subscribers":
        recipients = context.routing.subscriber_emails
    else:  # "operator" or anything else
        recipients = [context.routing.operator_email]

    # Send to each recipient
    for to_email in recipients:
        resend.Emails.send({...})
```

### 2d. Routing Model (`src/models/state.py`)

Current `Routing` model:

```python
class Routing(BaseModel):
    operator_email: str
    operator_sms: Optional[str] = None
    custodian_emails: List[str] = []      # exists but empty, no UI
    subscriber_emails: ???                 # DOES NOT EXIST YET
    observer_webhooks: List[str] = []
    reddit_targets: List[str] = []
    x_account_ref: Optional[str] = None
```

**Changes:**
- Add `subscriber_emails: List[str] = Field(default_factory=list)`
- Both `custodian_emails` and `subscriber_emails` need UI management

### 2e. Template Variables (`src/templates/context.py`)

These are the variables users can insert into their messages with `${{name}}`:

| Variable | Value | Example |
|----------|-------|---------|
| `project` | Project name | `continuity-orchestrator` |
| `stage` | Current stage | `REMIND_1` |
| `time_to_deadline_minutes` | Minutes left | `120` |
| `time_to_deadline_hours` | Hours left | `2` |
| `overdue_minutes` | Minutes overdue | `0` |
| `overdue_hours` | Hours overdue | `0` |
| `tick_id` | Current tick | `T-20260209-...` |
| `now_iso` | Current timestamp | `2026-02-09T...` |
| `plan_id` | Plan ID | `default` |
| `mode` | Operating mode | `renewable_countdown` |
| `action_id` | Action being run | `remind_email_primary` |
| `action_channel` | Target channel | `operator` |

---

## 3. UI Design

### 3a. Location

Third mode inside the Content tab: **Articles | Media | Messages**

### 3b. Left Sidebar

**Top section — Message list grouped by stage:**

```
── OK ──
  (no messages)

── REMIND_1 ──
  📧 reminder_basic → operator
  📧 subscriber_remind_1 → subscribers     ← user-created
  📱 remind_sms_early → operator            ← user-created

── REMIND_2 ──
  📧 reminder_strong → operator
  📱 reminder_sms → operator

── PRE_RELEASE ──
  📧 pre_release_notice → custodians

── PARTIAL ──
  🐦 partial_notice → public
  🤖 partial_notice → public

── FULL ──
  🐦 full_release → public
  🤖 full_release → public
  📰 full_article → public

[+ New Message]
```

Each item is clickable → loads into right panel for editing.

**Bottom section — Recipient Lists:**

```
── Subscribers ──
  alice@example.com  [✕]
  bob@example.com    [✕]
  [+ Add subscriber email]

── Custodians ──
  trusted@example.com  [✕]
  [+ Add custodian email]
```

### 3c. Right Panel (Editor)

When a message is selected:

```
┌─────────────────────────────────────────────────┐
│ 📧 reminder_basic                               │
│                                                  │
│ Stage: [REMIND_1 ▼]  Adapter: [email ▼]         │
│ Audience: [operator ▼]                           │
│                                                  │
│ ── Content ──                                    │
│ ┌──────────────────────────────────────────────┐ │
│ │ # ⏰ Scheduled Reminder — Renewal Due        │ │
│ │                                              │ │
│ │ Your continuity system deadline is approachi │ │
│ │ ...                                          │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ Insert: [project] [stage] [time_to_deadline_min] │
│         [time_to_deadline_hours] [tick_id] ...   │
│                                                  │
│ ── Preview ──                                    │
│ (Adapter-specific: rendered email / SMS with     │
│  char count / tweet with 280-limit / reddit      │
│  title+body)                                     │
│                                                  │
│                      [Discard] [💾 Save]         │
└─────────────────────────────────────────────────┘
```

**Adapter-specific preview behavior:**

- **Email** → Rendered markdown preview (like the styled HTML email)
- **SMS** → Plain text + character count + segment count (160/480 limits)
- **X** → Text + 280-character counter with warning color
- **Reddit** → Title (first `#` header) + body split preview

### 3d. New Message Flow

Click **[+ New Message]** → right panel shows creation form:

1. Pick stage from dropdown
2. Pick adapter from dropdown (email, sms, x, reddit)
3. Pick audience from dropdown (operator, subscribers, custodians, public)
4. Enter a template name (auto-suggested from selections)
5. Write content
6. Save → creates template file + adds action to `default.yaml`

---

## 4. Files to Create/Modify

### New Files

| File | Purpose |
|------|---------|
| `src/admin/routes_messages.py` | API: list messages, get/save/delete, manage subscriber/custodian lists, preview |
| `src/admin/templates/scripts/_messages.html` | JS for messages panel (hex escapes for `${{}}`, NO Jinja2 conflicts) |

### Modified Files

| File | Change |
|------|--------|
| `src/models/state.py` | Add `subscriber_emails: List[str]` to `Routing` |
| `src/adapters/email_resend.py` | Route by `channel` → operator / custodians / subscribers |
| `src/admin/server.py` | Import + register `messages_bp` blueprint |
| `src/admin/templates/index.html` | Include `_messages.html` script |
| `src/admin/templates/partials/_tab_content.html` | Add Messages toggle button, sidebar section, panel card **INSIDE the grid** |
| `src/admin/templates/scripts/_media.html` | Extend `contentSwitchMode()` for 'messages' mode |

### Critical Constraints

1. **Jinja2 escaping**: All `{{` in JS → use `'\x7b\x7b'` hex escapes. Never
   write literal `{{` in any `.html` file that Jinja2 processes.
2. **Layout**: Messages panel card is a **sibling of `content-editor-card` and
   `media-panel-card`**, INSIDE the `<div class="grid">`.
3. **Verify every step in the browser** before moving to the next file.

---

## 5. API Endpoints

```
GET  /api/content/messages/list
     → Returns all messages with stage/adapter/audience/template metadata
       (reads default.yaml + template files)

GET  /api/content/messages/<template_name>
     → Returns template content + metadata

POST /api/content/messages/save
     Body: { name, stage, adapter, channel, content }
     → Saves template file + updates default.yaml action

DELETE /api/content/messages/<template_name>
     → Removes template file + removes action from default.yaml

POST /api/content/messages/preview
     Body: { content, adapter }
     → Renders preview with current state variables, adapter-specific

GET  /api/content/messages/recipients
     → Returns { subscriber_emails: [...], custodian_emails: [...] }

POST /api/content/messages/recipients
     Body: { subscriber_emails: [...], custodian_emails: [...] }
     → Updates routing in state/current.json
```

---

## 6. Implementation Order

1. **Model change** — Add `subscriber_emails` to `Routing` (1 line)
2. **Email adapter fix** — Route by channel (small change in `execute()`)
3. **API routes** — `routes_messages.py` (the backend brain)
4. **HTML structure** — Toggle button + sidebar + panel card inside grid
5. **JavaScript** — `_messages.html` with hex escapes, adapter-aware editor
6. **Server registration** — Import + register blueprint
7. **Index include** — Add `_messages.html` to script includes
8. **Browser test** — Verify each piece works before next

Each step verified in browser before moving on.
