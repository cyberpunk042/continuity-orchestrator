# Messages Panel — Full Analysis

## 1. Current State

### Template files on disk

```
templates/
├── operator/                  ← Private (to the operator)
│   ├── reminder_basic.md      → "Your deadline is approaching" — email
│   ├── reminder_strong.md     → "URGENT, renew now" — email
│   └── reminder_sms.txt       → SMS body (must be <160 chars)
│
├── custodians/                ← Semi-private (to trusted contacts)
│   └── pre_release_notice.md  → Warning to custodians before escalation
│
└── public/                    ← PUBLIC (X, Reddit, GitHub Pages)
    ├── partial_notice.md      → "A process has entered automated phase"
    └── full_release.md        → "Full execution — overdue by X hours"
```

### Template content format

Templates use `${{variable}}` substitution syntax (NOT Jinja2 — different from site templates).
Variables available: `project`, `stage`, `tick_id`, `now_iso`, `time_to_deadline_minutes`,
`time_to_deadline_hours`, `overdue_minutes`, `overdue_hours`, `mode`, `armed`, `action_id`.

Example (`partial_notice.md`):
```
A previously configured continuity process has entered an automated phase.

Stage: ${{stage}}

Additional information may become available if escalation continues.
```

### How templates become posts

1. **Policy plan** (`policy/plans/default.yaml`) defines actions per stage
2. Each action references a `template: <name>` (e.g., `template: partial_notice`)
3. At execution time, `TemplateResolver` searches directories in order:
   `operator/ → custodians/ → public/ → articles/ → root/`
4. Variables are rendered: `${{stage}}` → "PARTIAL"
5. Each adapter parses the rendered content differently:
   - **Reddit**: First `#` heading → title, rest → body
   - **X/Twitter**: Strips headers, takes first paragraph, truncates to 280 chars
   - **Email**: First `#` heading → subject, rest → HTML body
   - **SMS**: Strips headers, takes raw text

### The problem

The public-facing templates (`partial_notice.md`, `full_release.md`) are extremely generic.
They don't sound like a real person. They're placeholder text that was written during initial
development and never personalized.

The operator has **no way to customize these messages** from the admin panel. They exist as
plain files on disk that can only be edited via git or SSH.

For the Reddit API request, the user described compelling scenarios like:
- "I was gone hiking X months and have not been able to check in."
- "I was recently reporting about ABC, and have not been able to check in."

These are great messages — but the system can't produce them right now because the
templates don't support this level of personalization.

---

## 2. Architecture of the Content Tab

### Current sub-panels

```
Content Tab
├── Mode toggle: [📄 Articles] [🖼️ Media]
├── Left sidebar
│   ├── Articles list (when Articles mode)
│   └── Media gallery (when Media mode)
├── Right panel
│   ├── Article editor (Editor.js, when Articles mode)
│   └── Media detail/upload (when Media mode)
└── Output terminal
```

### Mode switching mechanism

`contentSwitchMode(mode)` in `_media.html`:
- Toggle sidebar visibility: `content-sidebar-articles` vs `content-sidebar-media`
- Toggle right panel visibility: `content-editor-card` vs `media-panel-card`
- Toggle button active state: `content-mode-articles` vs `content-mode-media`
- Lazy-load data on first switch

### Key HTML element IDs

```
Tab:           tab-content
Sidebar:       content-list-card
  Articles:    content-sidebar-articles
  Media:       content-sidebar-media
Right panel:
  Articles:    content-editor-card
  Media:       media-panel-card
Mode buttons:  content-mode-articles, content-mode-media
```

### Content API blueprint

`/api/content/articles` — List, GET/PUT/DELETE articles
`/api/content/media/*` — Media CRUD + upload + preview

---

## 3. Design Decision: Where Does "Messages" Go?

### Option A: Third mode inside Content tab ✅ RECOMMENDED

```
Content Tab
├── Mode toggle: [📄 Articles] [🖼️ Media] [💬 Messages]  ← new button
├── Left sidebar
│   ├── Articles list
│   ├── Media gallery
│   └── Messages list (grouped by audience) ← new section
├── Right panel
│   ├── Article editor (Editor.js)
│   ├── Media detail/upload
│   └── Message editor (textarea + preview) ← new panel
└── Output terminal
```

**Why this works:**
- Consistent with existing UX pattern (mode toggle is already there)
- Templates are "content" — it's what gets sent out
- Reuses existing layout infrastructure
- No new top-level tab needed

### What changes are needed

#### A. HTML (`_tab_content.html`)
1. Add third mode button: `content-mode-messages`
2. Add sidebar section: `content-sidebar-messages`
3. Add right panel: `messages-panel-card`

#### B. JavaScript (new file: `_messages.html`)
1. `loadMessages()` — fetch template list from API
2. `renderMessagesList()` — render sidebar grouped by audience
3. `messagesSelectTemplate(name)` — load template content into editor
4. `messagesSave()` — save template back to disk
5. Update `contentSwitchMode()` to handle 'messages' mode

#### C. API (new blueprint or route additions)
1. `GET /api/content/messages` — List all templates with metadata
2. `GET /api/content/messages/<name>` — Get template content
3. `PUT /api/content/messages/<name>` — Save template content
4. `POST /api/content/messages/preview` — Render preview with current state

#### D. Update `contentSwitchMode()` in `_media.html`
Add handling for `mode === 'messages'` alongside `articles` and `media`

---

## 4. Messages Panel UI Design

### Left sidebar (when Messages mode)

```
💬 Messages                          [+ New]

┌─────────────────────────────────────────┐
│  📋 OPERATOR                            │
│  ├── reminder_basic       📧 email      │
│  ├── reminder_strong      📧 email      │
│  └── reminder_sms         📱 sms        │
│                                         │
│  📋 CUSTODIANS                          │
│  └── pre_release_notice   📧 email      │
│                                         │
│  📋 PUBLIC                              │
│  ├── partial_notice       🐦 X + 🤖 Reddit │
│  └── full_release         🐦 X + 🤖 Reddit │
└─────────────────────────────────────────┘
```

Each row shows:
- Template name
- Which adapters use it (derived from policy plan)
- Which stage(s) trigger it

### Right panel (when template selected)

```
┌──────────────────────────────────────────────────┐
│ ✏️ partial_notice                                │
│ Used by: x (PARTIAL), reddit (PARTIAL)           │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │ Template Content                             │ │
│ │                                              │ │
│ │ A previously configured continuity process   │ │
│ │ has entered an automated phase.              │ │
│ │                                              │ │
│ │ Stage: ${{stage}}                            │ │
│ │                                              │ │
│ │ Additional information may become available  │ │
│ │ if escalation continues.                     │ │
│ │                                              │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │ 📋 Available Variables                       │ │
│ │ ${{project}}  ${{stage}}  ${{tick_id}}       │ │
│ │ ${{time_to_deadline_hours}}                  │ │
│ │ ${{overdue_hours}}  ${{now_iso}}             │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │ 👁️ Preview (as rendered with current state)  │ │
│ │                                              │ │
│ │ A previously configured continuity process   │ │
│ │ has entered an automated phase.              │ │
│ │                                              │ │
│ │ Stage: REMIND_1                              │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │ 🐦 X Preview (280 char limit)               │ │
│ │ ────────────────────────────────────────     │ │
│ │ A previously configured continuity process   │ │
│ │ has entered an automated phase.              │ │
│ │ Stage: REMIND_1                              │ │
│ │ [43/280 chars]                               │ │
│ │                                              │ │
│ │ 🤖 Reddit Preview                           │ │
│ │ ──────────────                               │ │
│ │ Title: (no # heading → uses first line)      │ │
│ │ Body: A previously configured...             │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│                    [↩️ Discard]  [💾 Save]        │
└──────────────────────────────────────────────────┘
```

---

## 5. Data Flow Summary

```
User edits template in admin panel
    │
    ▼
PUT /api/content/messages/<name>  →  saves to templates/<dir>/<name>.<ext>
    │
    ▼
Next tick: engine/tick.py loads policy plan
    │
    ▼
Action has template: "partial_notice"
    │
    ▼
TemplateResolver.resolve_and_render()
    │
    ├── Finds templates/public/partial_notice.md
    ├── Loads content
    └── Renders ${{variables}} with build_template_context()
    │
    ▼
Adapter receives rendered content
    │
    ├── RedditAdapter._build_post() → parses into (title, body)
    ├── XAdapter._build_tweet() → extracts text, truncates to 280
    ├── EmailAdapter → extracts subject from header
    └── SMSAdapter → strips headers, takes raw text
    │
    ▼
Post/send
```

---

## 6. Implementation Order

### Phase 1: API routes (backend)
1. Add `/api/content/messages` blueprint
2. List templates with metadata (audience, used-by, stages)
3. Read/write template content
4. Preview endpoint (render with current state)

### Phase 2: HTML structure
1. Add Messages mode button to `_tab_content.html`
2. Add sidebar section for messages list
3. Add right panel for message editor

### Phase 3: JavaScript (`_messages.html`)
1. Load and render messages list (grouped by audience)
2. Select and edit template (textarea)
3. Per-adapter preview (X char count, Reddit title/body split)
4. Save with dirty tracking
5. Update `contentSwitchMode()` for messages

### Phase 4: Polish
1. Variable autocomplete/insertion buttons
2. Platform-specific warnings (SMS > 160 chars, X > 280 chars)
3. "Used by" badges showing which policy stages reference each template

---

## 7. Files to Touch

| File | Change |
|------|--------|
| `src/admin/routes_messages.py` | **NEW** — API blueprint for templates CRUD |
| `src/admin/server.py` | Register `messages_bp` blueprint |
| `src/admin/templates/partials/_tab_content.html` | Add Messages mode button + sidebar + panel |
| `src/admin/templates/scripts/_messages.html` | **NEW** — JS for messages panel |
| `src/admin/templates/scripts/_media.html` | Update `contentSwitchMode()` |
| `src/admin/templates/scripts/_tabs.html` | Add messages mode to tab switch handler |
| `src/admin/templates/admin.html` | Include `_messages.html` script |

### Files NOT touched
- Template resolver (already works)
- Adapter code (already parses templates correctly)
- Policy plans (action→template mapping stays the same)
- Engine tick.py (template loading already works)
