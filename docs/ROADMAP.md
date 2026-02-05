# Continuity Orchestrator — Roadmap

> **Last Updated**: 2026-02-04  
> **Status**: Production Ready → Expanding Capabilities

---

## 📍 Current State Assessment

### What We Have ✅

| Component | Status | Lines | Notes |
|-----------|--------|-------|-------|
| **Core Engine** | ✅ Working | ~600 | Tick lifecycle, rules, time eval |
| **State Management** | ✅ Working | ~200 | Pydantic models, JSON persistence |
| **Policy System** | ✅ Working | ~300 | YAML loader, rule evaluation |
| **Adapter Framework** | ✅ Working | ~1200 | 8 production adapters |
| **Template System** | ✅ Working | ~200 | Resolver, context, templates |
| **Audit Trail** | ✅ Working | ~180 | NDJSON append-only ledger |
| **CLI** | ✅ Enhanced | ~780 | 12 commands, health/metrics |
| **Site Generator** | ✅ Working | ~1100 | Static HTML, articles |
| **Reliability** | ✅ New | ~500 | Retry queue, circuit breakers |
| **Observability** | ✅ New | ~400 | Metrics, health checks |
| **Testing** | ✅ Strong | ~3000 | 255 tests, ~80% coverage |

**Total**: ~8,500 lines of Python across 25+ modules

### Adapters ✅

| Adapter | Status | Description |
|---------|--------|-------------|
| Email (Resend) | ✅ | Production email notifications |
| SMS (Twilio) | ✅ | SMS alerts with E.164 validation |
| X (Twitter) | ✅ | OAuth 1.0a, API v2 |
| Reddit | ✅ | PRAW multi-subreddit posting |
| Webhook | ✅ | HTTP POST integrations |
| GitHub Surface | ✅ | Gists/Pages artifacts |
| Persistence API | ✅ | Remote state sync |
| Article Publish | ✅ | Stage-based content |

### CLI Commands ✅

| Command | Description |
|---------|-------------|
| `tick` | Execute engine tick |
| `status` | Show system status |
| `health` | Health check with components |
| `metrics` | Prometheus/JSON metrics |
| `retry-queue` | Manage failed actions |
| `circuit-breakers` | View/reset breakers |
| `check-config` | Validate adapters |
| `build-site` | Generate static site |
| `renew` | Extend deadline |
| `set-deadline` | Adjust deadline |
| `reset` | Reset escalation |
| `init` | New project wizard |

---

## 🎯 Vision & Goals

### North Star
> A fully autonomous, policy-driven continuity system that can be:
> 1. **Forked** and customized by anyone
> 2. **Configured** entirely through YAML and templates
> 3. **Deployed** via GitHub Actions with zero infrastructure
> 4. **Triggered** automatically on schedule or via external events
> 5. **Published** to multiple channels (social, email, static site)

### Success Criteria for v1.0

- [ ] System runs autonomously via GitHub Actions
- [ ] At least 3 real adapter integrations working
- [ ] Static site generated at each escalation stage
- [ ] Full audit trail with queryable history
- [ ] Comprehensive tests (>80% coverage)
- [ ] Clear documentation for forking/customization
- [ ] Demo instance running publicly

---

## 📋 Development Phases

### Phase A: Hardening & Documentation (Current Priority)
**Goal**: Make the codebase production-ready and maintainable

| Task | Status | Est. Time |
|------|--------|-----------|
| A.1 — Add comprehensive docstrings | ✅ | 2h |
| A.2 — Add inline comments for complex logic | ✅ | 1.5h |
| A.3 — Create DEVELOPMENT.md guide | ✅ | 1h |
| A.4 — Update README.md with quick start | ✅ | 1h |
| A.5 — Add ARCHITECTURE.md (system overview) | ✅ | 1.5h |
| A.6 — Configure logging properly | ✅ | 0.5h |
| A.7 — Add error handling & validation | ✅ | 2h |

### Phase B: Testing Foundation
**Goal**: Establish confidence in the core logic

| Task | Status | Est. Time |
|------|--------|-----------|
| B.1 — Set up pytest infrastructure | ✅ | 0.5h |
| B.2 — Unit tests for time_eval.py | ✅ | 1h |
| B.3 — Unit tests for rules.py | ✅ | 1.5h |
| B.4 — Unit tests for state.py mutations | ✅ | 1h |
| B.5 — Integration test for tick lifecycle | ✅ | 2h |
| B.6 — Test policy loading edge cases | ✅ | 1h |
| B.7 — Add CI test workflow | ✅ | 0.5h |

### Phase C: Real Integrations
**Goal**: Connect to actual external services

| Adapter | Complexity | Dependencies | Status |
|---------|------------|--------------|--------|
| C.1 — Webhook | Low | httpx | ✅ Done |
| C.2 — Email (Resend) | Low | resend | ✅ Done |
| C.3 — GitHub Surface | Medium | httpx | ✅ Done |
| C.4 — Persistence API | Low | httpx | ✅ Done |
| C.5 — Article Publish | Low | site generator | ✅ Done |
| C.6 — SMS (Twilio) | Medium | twilio | ⬜ |
| C.7 — X (Twitter) | High | OAuth, tweepy | ⬜ |
| C.8 — Reddit | High | OAuth, praw | ⬜ |

### Phase D: Triggers & Automation
**Goal**: Multiple ways to trigger actions beyond CRON

| Task | Description |
|------|-------------|
| D.1 — **Webhook Trigger** | External POST to trigger tick |
| D.2 — **Issue/PR Trigger** | GitHub events as signals |
| D.3 — **Manual Dispatch** | Parameterized workflow runs |
| D.4 — **Renewal API** | Secure endpoint to extend deadline |
| D.5 — **Health Check** | Status endpoint for monitoring |

### Phase E: Asset & Content Management
**Goal**: Structured management of publishable content

| Feature | Description |
|---------|-------------|
| E.1 — **Post Registry** | Pre-authored posts per stage |
| E.2 — **Article Store** | Long-form content with metadata |
| E.3 — **Message Queue** | Ordered messages for escalation |
| E.4 — **Asset Versioning** | Track changes to published content |
| E.5 — **Draft System** | Preview before publish |

### Phase F: Static Site & Public Surface
**Goal**: Generate and publish a public-facing site

| Task | Description | Status |
|------|-------------|--------|
| F.1 — Site generator (Markdown → HTML) | SiteGenerator class | ✅ Done |
| F.2 — GitHub Pages deployment | deploy-site.yml workflow | ✅ Done |
| F.3 — Status page (current state, timeline) | index.html, timeline.html | ✅ Done |
| F.4 — Archive page (historical escalations) | archive/*.html | ✅ Done |
| F.5 — RSS/Atom feed for updates | feed.xml | ✅ Done |

### Phase G: Forkability & Customization
**Goal**: Make it easy for others to create their own instance

| Task | Description |
|------|-------------|
| G.1 — Template repository setup | |
| G.2 — `init` command to bootstrap new instance | |
| G.3 — Configuration wizard | |
| G.4 — Example configurations (minimal, full) | |
| G.5 — Theming system for templates | |

---

## 🏗️ Architecture Improvements Needed

### Configuration
- [ ] Environment-based config (dev/prod)
- [ ] Secret injection from GitHub Secrets
- [ ] Override constants via env vars
- [ ] Multi-plan support (different escalation paths)

### Reliability
- [ ] Retry logic for failed adapters
- [ ] Circuit breaker for external services
- [ ] Fallback actions on failure
- [ ] State backup/recovery

### Observability
- [ ] Structured logging (JSON)
- [ ] Metrics (tick duration, actions executed)
- [ ] Alert on critical failures
- [ ] Dashboard/visualization

### Security
- [ ] Renewal authentication
- [ ] Rate limiting
- [ ] Signature verification for webhooks
- [ ] Audit log integrity (hash chain)

---

## 📊 Immediate Next Steps (This Session)

1. **Cleanup sweep** — Add missing docstrings and comments
2. **Create DEVELOPMENT.md** — How to set up, run, test
3. **Update README.md** — Project overview, quick start
4. **Test coverage plan** — Define what to test first

---

## 🔮 Long-Term Vision

### For Personal Use
- Autonomous system running 24/7 on GitHub Actions
- Private renewal interface (simple, secure)
- Notification escalation to trusted contacts
- Public disclosure if renewal fails

### For Open Source
- Template repository for easy forking
- Comprehensive documentation
- Active community of customizers
- Multiple example configurations

### For the Ecosystem
- Proof of concept for "dead man's switch" pattern
- Reference implementation for policy-driven automation
- Educational resource for Python/GitHub Actions

---

## Notes

- **We stay realistic** — Building incrementally, not everything at once
- **We plan ahead** — Vision is clear, execution is phased
- **We prioritize** — Hardening before features, stability before scale
- **We document** — Code without docs is technical debt

---

*This roadmap is a living document. Update as we progress.*
