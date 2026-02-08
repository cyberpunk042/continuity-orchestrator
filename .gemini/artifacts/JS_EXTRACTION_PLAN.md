# JavaScript Extraction Plan — Dependency-Driven

> Generated from automated call-graph and shared-state analysis of
> `src/admin/static/index.html` (4,031 script lines, 96 top-level declarations).

## Current State

The `<script>` block has been left intact inside `templates/index.html`.
HTML markup is already extracted into 8 Jinja2 partials. Rendered output is
byte-for-byte identical to the original. All 255 tests pass.

---

## 1. Cross-Section Dependency Matrix

```
Section              Depends On
─────────────────    ──────────────────────────────────────────
GLOBALS              ✓ self-contained
THEME                → GITHUB_MENU
GITHUB_MENU          → LANG
LANG                 → AUTO_REFRESH, INTEGRATIONS, MIRROR, SECRETS, TAB_SWITCH, WIZARD
TAB_SWITCH           → CMD_UTILS, GLOBALS, LANG, SECRETS, WIZARD
DASHBOARD            ✓ self-contained
SECRETS              → DASHBOARD, GLOBALS, TAB_SWITCH, WIZARD
CMD_UTILS            → AUTO_REFRESH, GIT_STATUS, SECRETS
GIT_STATUS           → AUTO_REFRESH, CMD_UTILS, MIRROR
INTEGRATIONS         → GIT_STATUS, GLOBALS, LANG, MIRROR, TAB_SWITCH
MIRROR               → AUTO_REFRESH, GLOBALS, INTEGRATIONS, LANG, TAB_SWITCH, WIZARD
WIZARD               → GLOBALS, MIRROR, TAB_SWITCH
AUTO_REFRESH         → CMD_UTILS, GLOBALS, LANG, MIRROR, TAB_SWITCH, WIZARD
```

## 2. Section Sizes

```
Section              Lines   Declarations
─────────────────    ─────   ────────────
GLOBALS                 25         5       (appData, envData, ghAuthenticated, etc.)
THEME                   40         1       (toggleTheme)
GITHUB_MENU             25         2       (updateGhMenu, restore-theme-on-load)
LANG                    80         4       (LANGUAGES, toggleLangDropdown, selectLang, etc.)
TAB_SWITCH              74         4       (switchTab, goToWizardStep, dirty wrapper)
DASHBOARD              226         4       (loadStatus, renderDashboard)
SECRETS              1,070        23       (loadSecretsForm, pushSecrets, syncEnvToGithub, etc.)
CMD_UTILS               60         3       (runCmd, runCmdWithSync, doGitSync)
GIT_STATUS              85         2       (loadGitStatus, dashboardGitSync)
INTEGRATIONS           180         3       (INTEGRATIONS const, loadIntegrations, runIntegrationTest)
MIRROR                 490        15       (loadMirrorStatus, mirrorStream, mirrorClean, archive*, etc.)
WIZARD               1,245        21       (wizardSteps, renderWizard, deadline, triggers, etc.)
AUTO_REFRESH           500        15       (scheduleStatus, autoFetch, boot sequence, wizard render)
```

## 3. Shared Globals by Section

```
Section          Globals Read/Written
─────────────    ──────────────────────────────────────────
GLOBALS          appData, envData, ghAuthenticated (declarations)
LANG             activeTab, currentWizardStep, secretsLoaded
TAB_SWITCH       activeTab, appData, envData, ghAuthenticated, secretsDirty, secretsInitialValues, wizardDirty
DASHBOARD        currentTarget, ghSecrets, ghVariables
SECRETS          appData, currentTarget, envData, ghSecrets, ghVariables, secretsDirty, secretsInitialValues, secretsLoaded
CMD_UTILS        (no direct global access — pure utility)
GIT_STATUS       (no direct globals — reads from DOM)
INTEGRATIONS     appData, envData
MIRROR           _mirrorEventSource, appData, envData, wizardData
WIZARD           currentWizardStep, envData, wizardData, wizardDirty
AUTO_REFRESH     _fetchTimer, _statusTimer, currentWizardStep, envData, wizardData, wizardDirty
```

## 4. Extraction Safety Scores

Lower score = safer to extract first. Score = outbound deps + inbound deps.

```
Score  Section          Out  In   Assessment
─────  ───────────────  ───  ───  ──────────────────────
  1    DASHBOARD          0    1   🟢 SAFE — zero outbound deps
  1    THEME              1    0   🟢 SAFE — only calls updateGhMenu
  2    GITHUB_MENU        1    1   🟢 SAFE — small, clear boundary
  5    GIT_STATUS         3    2   🟡 MODERATE — calls into CMD_UTILS, MIRROR
  6    CMD_UTILS          3    3   🔴 COMPLEX — shared utility, called by many
  7    INTEGRATIONS       5    2   🔴 COMPLEX — wide fan-out
  7    SECRETS            4    3   🔴 COMPLEX — huge, touches many globals
  8    WIZARD             3    5   🔴 COMPLEX — many callers
 10    AUTO_REFRESH       6    4   🔴 COMPLEX — orchestrates everything
 11    LANG               6    5   🔴 COMPLEX — switchTab lives here, called everywhere
 11    MIRROR             6    5   🔴 COMPLEX — wide fan-out + fan-in
 11    TAB_SWITCH         5    6   🔴 COMPLEX — core routing, everyone depends on it
```

---

## 5. Strategy: Jinja2 Script Partials (Not Separate .js Files)

### Why Jinja2 `{% include %}` for scripts, NOT separate `.js` files?

1. **All functions share a single global scope** inside one `<script>` tag —
   extracting to separate `.js` files would require converting to ES modules
   (import/export), which is a much larger refactor with real regression risk.

2. **Jinja2 `{% include %}` is a text substitution** — the rendered HTML is
   byte-for-byte the same as having the code inline. Zero behavioral change.

3. **No build step needed** — Flask's Jinja2 handles it at serve time.

### File structure

```
templates/
├── index.html              ← include directives + boot code
├── partials/               ← HTML partials (done ✅)
│   ├── _head.html
│   ├── _nav.html
│   ├── _tab_dashboard.html
│   ├── _tab_secrets.html
│   ├── _tab_commands.html
│   ├── _tab_debugging.html
│   ├── _tab_integrations.html
│   └── _tab_wizard.html
└── scripts/                ← JS partials (TO DO)
    ├── _globals.html       ← <script> tag + global state
    ├── _theme.html         ← theme toggle + github menu
    ├── _lang.html          ← language selector
    ├── _tabs.html          ← tab switching + dirty guard
    ├── _dashboard.html     ← loadStatus + renderDashboard
    ├── _secrets.html       ← all secrets management
    ├── _commands.html      ← runCmd, runCmdWithSync, doGitSync
    ├── _git_status.html    ← loadGitStatus, dashboardGitSync
    ├── _integrations.html  ← loadIntegrations, runIntegrationTest
    ├── _mirror.html        ← mirror + archive functions
    ├── _wizard.html        ← wizard steps + deadline + triggers
    └── _boot.html          ← auto-refresh + DOMContentLoaded + </script>
```

---

## 6. Extraction Order (Safe → Complex)

### Phase 1 — Zero-risk extractions (🟢 SAFE)

These sections have ≤ 2 cross-section dependencies and small surface area:

1. **GLOBALS** (25 lines) → `scripts/_globals.html`
   - Contains: `<script>`, `appData`, `envData`, `ghAuthenticated`
   - Risk: None — pure declarations, no function calls

2. **THEME** (40 lines) → `scripts/_theme.html`
   - Contains: `toggleTheme`, `updateGhMenu`, theme restore
   - Deps: calls `updateGhMenu` (included in same file)
   - Risk: None

3. **DASHBOARD** (226 lines) → `scripts/_dashboard.html`
   - Contains: `loadStatus`, `renderDashboard`
   - Deps: ZERO outbound. Only called by TAB_SWITCH
   - Risk: None

### Phase 2 — Low-risk extractions (🟡 MODERATE)

4. **LANG** (80 lines) → `scripts/_lang.html`
   - Contains: `LANGUAGES`, `toggleLangDropdown`, `selectLang`, `googleTranslateElementInit`
   - Risk: Low — self-contained UI logic

5. **TAB_SWITCH** (74 lines) → `scripts/_tabs.html`
   - Contains: `switchTab`, `goToWizardStep`, dirty wrapper
   - IMPORTANT: `switchTab` is THE most-called function — extract position matters

6. **CMD_UTILS** (60 lines) → `scripts/_commands.html`
   - Contains: `runCmd`, `runCmdWithSync`, `doGitSync`
   - Risk: Shared by commands tab, secrets, wizard — but pure functions

7. **GIT_STATUS** (85 lines) → `scripts/_git_status.html`
   - Contains: `loadGitStatus`, `dashboardGitSync`
   - Risk: Low — clear integration points

### Phase 3 — Larger, cohesive extractions (🔴 COMPLEX but contained)

8. **SECRETS** (1,070 lines) → `scripts/_secrets.html`
   - The biggest single section. Very cohesive internally.
   - Risk: Moderate — touches many globals, but all secrets-specific

9. **INTEGRATIONS** (180 lines) → `scripts/_integrations.html`
   - Contains: `INTEGRATIONS` const, `loadIntegrations`, `runIntegrationTest`
   - Risk: Moderate — depends on MIRROR for `getLastTestHtml`

10. **MIRROR** (490 lines) → `scripts/_mirror.html`
    - Contains: mirror status, streaming, clean, archive
    - Risk: Moderate — wide coupling but cohesive

### Phase 4 — Final extraction

11. **WIZARD** (1,245 lines) → `scripts/_wizard.html`
    - Contains: wizard steps, deadline management, trigger/return controls
    - Risk: High — most entangled, many inbound callers

12. **AUTO_REFRESH** (500 lines) → `scripts/_boot.html`
    - Contains: scheduleStatus, autoFetch, boot sequence, `</script>`
    - Risk: Must be extracted LAST — orchestrates everything

---

## 7. Verification Protocol (for each extraction)

```
1. Extract lines N-M to scripts/_xxx.html
2. Replace lines N-M in index.html with {% include 'scripts/_xxx.html' %}
3. Run: python -c "... byte-for-byte comparison ..."       → must print PERFECT
4. Run: python -m pytest -q                                → must print 255 passed
5. Manual browser check (if significant)                   → all tabs functional
```

---

## 8. Key Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Off-by-one in line extraction | Use Python script, not manual sed; verify byte-identical |
| Jinja2 `{% %}` conflicts in JS | Pre-checked: original JS has no `{% %}` or `{{ }}` patterns |
| Function hoisting changes | All `{% include %}` is text concat — same `<script>` scope |
| Extra/missing newlines | Python script preserves exact line boundaries |
| Circular dependencies | No circular deps exist (verified by call graph) |

---

## 9. What We're NOT Doing (and Why)

- ❌ **ES modules** — Would require `<script type="module">`, import/export everywhere, break all inline `onclick` handlers. Massive regression risk.
- ❌ **Webpack/Vite bundling** — Introduces a build step. Overkill for an admin panel.
- ❌ **Moving JS to separate `.js` files** — Would break the shared global scope. All functions call each other freely across sections.
- ❌ **Refactoring logic** — We are ONLY splitting files. No behavioral changes. No renaming. No restructuring. The goal is organization, not rewriting.
