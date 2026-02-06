# Continuity Orchestrator — Cleanup & Refactor Plan

**Created:** 2026-02-06  
**Goal:** Make the repository easy to fork, setup, and test at multiple layers

---

## 1. Current Structure Analysis

### 1.1 Entry Points (User Layers)

| Layer | Entry Point | Purpose | Status |
|-------|-------------|---------|--------|
| **L1 - Demo** | `./demo.sh` | See it work (30s) | ✅ Good |
| **L2 - Setup** | `./setup.sh` | Interactive wizard | ✅ Good but large (565 lines) |
| **L3 - Docker** | `docker compose up` | Test with containers | ⚠️ Complex (386 lines, 3 modes) |
| **L4 - CLI** | `python -m src.main` | Full control | ✅ Good (30 commands) |
| **L5 - Management** | `./manage.sh` | Menu-driven | 🔄 Overlap with CLI |
| **L6 - GitHub Actions** | `.github/workflows/` | Production | ✅ Good |

### 1.2 Documentation Structure

| Document | Purpose | Status |
|----------|---------|--------|
| `README.md` | Overview & quick start | ✅ Good |
| `docs/QUICKSTART.md` | 5-min setup | ✅ Good |
| `docs/CONFIGURATION.md` | All options | ✅ Exists |
| `docs/DEPLOYMENT.md` | Production setup | ✅ Exists |
| `docs/ARCHITECTURE.md` | How engine works | ✅ Exists |
| `docs/DEVELOPMENT.md` | Contributing | ✅ Exists |
| `docs/ROADMAP.md` | Future plans | ⚠️ May be outdated |
| `docs/IMPLEMENTATION_PLAN.md` | Internal | ❌ Should be in archive |
| `docs/AUTHORING.md` | Content creation | ⚠️ Niche |
| `docs/specs/` | Technical specs | ⚠️ Internal |
| `docs/legacy/` | Old docs | ❌ Should be archived |

### 1.3 Scripts Directory

| Script | Purpose | Status |
|--------|---------|--------|
| `scripts/docker-local.sh` | Run Docker standalone | ✅ New |
| `scripts/docker-sync.sh` | Run Docker with git-sync | ✅ New |
| `scripts/rebuild-site.sh` | Rebuild static site | ✅ Simple |
| `scripts/run_tick.sh` | Run single tick | ⚠️ Overlap with CLI |
| `scripts/demo_escalation.sh` | Demo flow | ⚠️ Overlap with demo.sh |
| `scripts/docker_init.py` | Docker state init | ✅ Internal |

### 1.4 Examples Directory

| Example | Purpose | Status |
|---------|---------|--------|
| `examples/minimal/` | Bare minimum | ✅ Good |
| `examples/deadman-switch/` | Classic use case | ✅ Good |
| `examples/newsletter/` | Scheduled publish | ⚠️ Underdeveloped |

### 1.5 Source Code Structure

```
src/
├── main.py (1671 lines)      # ⚠️ Too large - should be split
├── adapters/ (12 files)      # ✅ Good - modular
├── engine/ (5 files)         # ✅ Good
├── models/ (3 files)         # ✅ Good
├── site/ (4 files)           # ✅ Good
├── policy/ (3 files)         # ✅ Good
├── templates/ (3 files)      # ✅ Good
├── persistence/ (3 files)    # ✅ Good
├── config/ (3 files)         # ✅ Good
├── observability/ (3 files)  # ✅ Good
└── reliability/ (3 files)    # ✅ Good
```

### 1.6 Test Coverage

- **255 tests** collected
- Tests exist for: adapters, engine, policy, site, state, validation
- ❌ Missing: test for release trigger flow

---

## 2. Identified Issues

### 2.1 Critical Issues

1. **No DISCLAIMER** - Must add legal disclaimer for deadman switch use
2. **base.html lint errors** - Jinja template causing false positives
3. **Release trigger not tested** - New feature lacks tests
4. **Renewal clears triggered but trigger remains set** - Logic confirmed correct

### 2.2 Structural Issues

1. **`main.py` too large** - 1671 lines, 30 commands; should split into command groups
2. **Script overlap** - Multiple ways to do same thing
3. **Docker complexity** - 3 modes in one docker-compose.yml
4. **docs/legacy still exists** - Should archive or remove
5. **docs/IMPLEMENTATION_PLAN.md** - Internal, doesn't belong in user docs

### 2.3 Onboarding Friction

1. **No CONTRIBUTING.md** - Should exist for OSS
2. **No clear "fork & customize" guide** - README jumps to setup
3. **Examples need polish** - newsletter example is incomplete
4. **scripts/README.md outdated** - Doesn't document new docker scripts

### 2.4 Missing Documentation

1. **RELEASE_TRIGGER.md** - How manual release works
2. **FORKING_GUIDE.md** - Step-by-step to fork and run your own
3. **SECURITY.md** - Security considerations and best practices
4. **DISCLAIMER.md** - Legal disclaimer

---

## 3. Cleanup Plan

### Phase 1: Critical Additions (PRIORITY)

```
[ ] Add DISCLAIMER.md with full legal notice
[ ] Add DISCLAIMER section to README.md header
[ ] Add SECURITY.md with security considerations
[ ] Add tests for release trigger flow
```

### Phase 2: Documentation Cleanup

```
[ ] Create FORKING_GUIDE.md - "Fork & Deploy Your Own"
[ ] Create docs/RELEASE_TRIGGER.md - Manual disclosure docs
[ ] Move docs/IMPLEMENTATION_PLAN.md to archive/
[ ] Move docs/legacy/ to archive/
[ ] Update docs/ROADMAP.md or remove if outdated
[ ] Create CONTRIBUTING.md for OSS contributions
```

### Phase 3: Script Consolidation

```
[ ] Remove scripts/run_tick.sh (use CLI directly)
[ ] Remove scripts/demo_escalation.sh (use demo.sh)
[ ] Update scripts/README.md with docker helpers
[ ] Ensure all scripts have proper documentation headers
```

### Phase 4: Source Code Refactor

```
[ ] Split main.py into command modules:
    - cli/core.py (tick, status, init, reset)
    - cli/release.py (trigger-release, renew)
    - cli/deploy.py (build-site, export-secrets)
    - cli/test.py (test_*, health)
    - cli/observability.py (metrics, circuit-breakers)
```

### Phase 5: Docker Simplification

```
[ ] Split docker-compose.yml into:
    - docker-compose.yml (basic/test mode)
    - docker-compose.sync.yml (git-sync mode)
[ ] Update README and DEPLOYMENT docs
```

### Phase 6: Examples Polish

```
[ ] Complete newsletter example
[ ] Add enterprise/ example with all features
[ ] Ensure each example has its own README
```

### Phase 7: Web Wizard (Future)

```
[ ] Create static HTML setup page in templates/wizard/
[ ] Generate config via browser form
[ ] Export to .env or JSON format
[ ] Can run locally or on GitHub Pages
```

---

## 4. File Changes Summary

### Files to CREATE

| File | Purpose |
|------|---------|
| `DISCLAIMER.md` | Legal disclaimer (ROOT) |
| `SECURITY.md` | Security best practices |
| `CONTRIBUTING.md` | OSS contribution guide |
| `docs/FORKING_GUIDE.md` | Fork your own guide |
| `docs/RELEASE_TRIGGER.md` | Manual release docs |
| `tests/test_release_trigger.py` | Release feature tests |

### Files to MOVE/ARCHIVE

| From | To |
|------|-----|
| `docs/IMPLEMENTATION_PLAN.md` | `archive/IMPLEMENTATION_PLAN.md` |
| `docs/legacy/` | `archive/legacy/` |

### Files to DELETE (redundant)

| File | Reason |
|------|--------|
| `scripts/run_tick.sh` | Use `python -m src.main tick` |
| `scripts/demo_escalation.sh` | Use `./demo.sh` |

### Files to UPDATE

| File | Changes |
|------|---------|
| `README.md` | Add disclaimer banner, update structure |
| `scripts/README.md` | Document docker-local.sh, docker-sync.sh |
| `examples/newsletter/README.md` | Complete the example |

---

## 5. Execution Order

1. **DISCLAIMER.md** - Legal protection first
2. **SECURITY.md** - Important for production use
3. **README.md** - Add disclaimer banner
4. **Archive internal docs** - Clean up docs/
5. **FORKING_GUIDE.md** - Enable self-hosting
6. **RELEASE_TRIGGER.md** - Document new feature
7. **CONTRIBUTING.md** - OSS-ready
8. **Update scripts/README.md** - Current documentation
9. **Test coverage** - Add release trigger tests
10. **Source refactor** - Optional but recommended

---

## 6. User Experience Layers (Final Vision)

```
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 0: READ                                                    │
│ ────────────────────────────────────────────────────────────────│
│ README.md → DISCLAIMER.md → QUICKSTART.md → FORKING_GUIDE.md    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 1: TRY                                                     │
│ ────────────────────────────────────────────────────────────────│
│ ./demo.sh        (30 seconds - see it work)                     │
│ docker compose up (2 minutes - run locally)                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 2: CONFIGURE                                               │
│ ────────────────────────────────────────────────────────────────│
│ ./setup.sh       (5 minutes - interactive wizard)               │
│ [FUTURE] Web wizard at /wizard.html                             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 3: DEPLOY                                                  │
│ ────────────────────────────────────────────────────────────────│
│ GitHub Actions   (Production - 15min ticks)                     │
│ Docker git-sync  (Self-hosted - persistent)                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 4: OPERATE                                                 │
│ ────────────────────────────────────────────────────────────────│
│ ./manage.sh      (Menu-driven operations)                       │
│ python -m src.main (Full CLI control)                           │
│ Web dashboard    (Status view at /countdown.html)               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 5: CUSTOMIZE                                               │
│ ────────────────────────────────────────────────────────────────│
│ examples/        (Copy and modify)                              │
│ policy/          (Edit rules, plans)                            │
│ templates/       (Custom messages)                              │
│ src/adapters/    (Add new integrations)                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. Approval

Shall I proceed with this plan?

- [ ] Start with Phase 1 (DISCLAIMER, SECURITY)
- [ ] Start with Phase 2 (Documentation)
- [ ] Start with all phases in order
- [ ] Modify the plan first
