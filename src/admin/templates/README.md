# Admin Panel Templates

> Jinja2 template structure for the local admin web interface.

---

## Architecture Overview

The admin UI is a **single-page application** rendered server-side by Flask/Jinja2.  
All HTML is assembled from partials and scripts via `{% include %}` directives in `index.html`.

```
index.html                          ← Main entry point
├── partials/_head.html             ← <DOCTYPE>, <head>, CSS link
├── partials/_nav.html              ← Tab navigation bar
├── partials/_tab_*.html            ← Tab content panels (HTML structure)
├── partials/_vault.html            ← Vault overlay & lock modal (HTML)
├── scripts/_globals.html           ← Opens <script>, global state vars
├── scripts/_theme.html             ← Theme toggle logic
├── scripts/_lang.html              ← Language/translate logic
├── scripts/_tabs.html              ← Tab switching logic
├── scripts/_dashboard.html         ← Dashboard rendering
├── scripts/_secrets.html           ← Secrets management
├── scripts/_commands.html          ← Command center
├── scripts/_git_status.html        ← Git status panel
├── scripts/_integrations.html      ← Integration panels
├── scripts/_content.html           ← Content/article editor
├── scripts/_mirror.html            ← Mirror management
├── scripts/_wizard.html            ← Setup wizard
├── scripts/_vault.html             ← Vault lock/unlock logic
├── scripts/_boot.html              ← Boot sequence, closes </script>
└── (Google Translate, </body>)
```

---

## ⚠️ Critical: Script File Convention

### The `scripts/` directory uses a **shared `<script>` block** pattern.

All files in `scripts/` are **raw JavaScript** — they do **NOT** contain their own
`<script>` or `</script>` tags (with two exceptions noted below).

The script tag lifecycle:

| File | Role |
|------|------|
| `_globals.html` | **Opens** the `<script>` tag, declares global vars |
| `_theme.html` through `_vault.html` | Raw JS functions — no tags |
| `_boot.html` | Boot logic, **closes** `</script>` |

### Rules for script files:

1. **Never add `<script>` or `</script>` tags** in a script file
2. **Never add HTML elements** in a script file — use `partials/` for HTML
3. All functions share the **same global scope** — no modules
4. Use `// ── Section Name ─────` comment headers for organization
5. Indent with 8 spaces (matching the `<script>` block indentation)
6. Jinja2 template syntax is active — `<` in JS comparisons works fine
   (confirmed: `_dashboard.html` uses `ttd < 60` without issues)
7. Avoid Jinja2 delimiters (`{{ }}`, `{% %}`) unless intentionally using templating

### Adding a new script module:

1. Create `scripts/_mymodule.html` with raw JS only
2. Include it in `index.html` between `_wizard.html` and `_boot.html`
3. If you need HTML (modals, overlays), create `partials/_mymodule.html` separately

---

## The `partials/` Directory

Partials contain **HTML structure** — the visual layout for each tab and component.

| File | Content |
|------|---------|
| `_head.html` | Document head, meta tags, CSS link |
| `_nav.html` | Top navigation tabs, controls, theme/vault buttons |
| `_tab_dashboard.html` | Dashboard tab container |
| `_tab_secrets.html` | Secrets tab container |
| `_tab_commands.html` | Commands tab + command cards |
| `_tab_debugging.html` | Debugging tab with deadline management |
| `_tab_integrations.html` | Integrations tab container |
| `_tab_content.html` | Content editor tab with article list, editor, metadata |
| `_tab_wizard.html` | Setup wizard tab container |
| `_vault.html` | Vault unlock overlay + lock modal (full-screen) |

### Rules for partials:

1. Partials contain **HTML only** — no `<script>` tags
2. Inline `onclick`, `onkeydown` handlers are OK (they reference functions from scripts)
3. Use CSS custom properties (`var(--bg-card)` etc.) for theming
4. Inline styles are used for component-specific layout

---

## Vault UI Components

The vault has two HTML components (in `partials/_vault.html`):

### Unlock Overlay (`#vault-overlay`)
- Full-screen overlay with `z-index: 10000`
- Blocks **all** UI interaction when vault is locked
- Shows passphrase input and unlock button
- Displayed on page load if `.env.vault` exists without `.env`

### Lock Modal (`#vault-lock-modal`)
- Secondary modal for choosing a passphrase to lock
- Includes passphrase confirmation
- Auto-lock timeout selector (15/30/60 min or disabled)

### Vault Button (`#vault-toggle`)
- In the nav bar (`_nav.html`)
- Shows 🔒 when locked, 🔓 when unlocked
- Tooltip shows current auto-lock timeout

---

## Data Flow

```
User clicks tab → switchTab('tabname')           → shows #tab-tabname
Tab loads data  → fetch('/api/...')               → renders into DOM
User action     → onclick="someFunction()"        → API call → re-render
Vault lock      → overlay shown, API blocked      → passphrase required
Server shutdown → auto-lock fires                 → .env encrypted
```

---

## Common Patterns

### Rendering dynamic content
Scripts use template literals to build HTML and assign to `.innerHTML`:
```javascript
dashboard.innerHTML = `
    <div class="card">
        <h2>${data.title}</h2>
        ...
    </div>
`;
```

### API calls
All API calls use `fetch()` with JSON:
```javascript
const resp = await fetch('/api/endpoint', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key: value }),
});
const data = await resp.json();
```

### Polling
Status/git/env data refreshes on a timer (see `_boot.html`):
- Status: every 30s
- Git fetch: every 60s
- Env read: every 30s
- Vault status: every 10s
