# Implementation Plan: Remaining System Components

**Created**: 2026-02-04  
**Last Updated**: 2026-02-04  
**Status**: In Progress

---

## 🎯 Overview

This document outlines the remaining components needed to complete the continuity-orchestrator system. The focus is on:

1. **Stage-based content publishing** — Which articles become public at which stage
2. **Renewal flow** — Countdown display, code entry, validation
3. **Configuration validation** — Detecting missing/incomplete adapter configs
4. **Adapter logging** — Clear feedback on what's configured vs attempted
5. **User guidance** — Editor.js authoring, setup wizard

---

## 📋 Component Analysis

### Current State

```
┌────────────────────────────────────────────────────────────────┐
│                    WHAT WE HAVE                                │
├────────────────────────────────────────────────────────────────┤
│ ✅ 8-phase tick lifecycle                                      │
│ ✅ Policy-driven state machine (6 states)                      │
│ ✅ 5 real adapters (webhook, email, GitHub, persistence, site) │
│ ✅ Editor.js content pipeline                                  │
│ ✅ Static site generator with dark theme                       │
│ ✅ GitHub Actions CI/CD                                        │
│ ✅ 79 passing tests                                            │
│ ✅ Stage-based article visibility (manifest.yaml)              │
│ ✅ Renewal workflow & CLI command                              │
│ ✅ Configuration validator & check-config command              │
│ ✅ Status CLI command                                          │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│                    WHAT'S REMAINING                            │
├────────────────────────────────────────────────────────────────┤
│ ⬜ Countdown/status public page with code entry                │
│ ⬜ Enhanced adapter logging in tick execution                  │
│ ⬜ Setup wizard / init command                                 │
│ ⬜ SMS adapter (Twilio)                                        │
│ ⬜ X/Reddit adapters (OAuth)                                   │
│ ⬜ Documentation (AUTHORING.md, CONFIGURATION.md)              │
└────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Component 1: Stage-Based Article Publishing

### Problem
Currently, all articles in `content/articles/` are always published. We need articles to appear only at specific escalation stages.

### Solution

**Content manifest** that maps articles to stages:

```yaml
# content/manifest.yaml
articles:
  - slug: partial_notice
    title: Initial Notice
    visibility:
      stage: PARTIAL      # Only visible at PARTIAL and beyond
      include_in_site: true
      
  - slug: full_disclosure
    title: Full Disclosure Statement
    visibility:
      stage: FULL         # Only visible at FULL
      include_in_site: true
      
  - slug: about
    title: About This System
    visibility:
      stage: OK           # Always visible
      include_in_site: true
```

**Implementation**:

1. Create `content/manifest.yaml` schema
2. Update `SiteGenerator` to filter articles by current stage
3. Add `stage_order >= article_required_stage` logic
4. Generate placeholder pages for not-yet-released articles

```python
# In site generator
def _should_publish_article(self, article_stage: str, current_stage: str) -> bool:
    """Determine if article should be published based on current state."""
    stage_order = {"OK": 0, "REMIND_1": 10, "REMIND_2": 20, 
                   "PRE_RELEASE": 30, "PARTIAL": 40, "FULL": 50}
    return stage_order.get(current_stage, 0) >= stage_order.get(article_stage, 50)
```

### Files to Create/Modify
- `content/manifest.yaml` — Article metadata and visibility rules
- `src/site/manifest.py` — Load and validate manifest
- `src/site/generator.py` — Filter articles by stage
- `tests/test_manifest.py` — Test visibility logic

---

## 🔐 Component 2: Renewal Flow

### Problem
No mechanism exists to:
1. Display the countdown publicly
2. Accept a renewal code
3. Validate the code and reset the timer

### Solution Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       RENEWAL FLOW                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   PUBLIC SITE                  GITHUB ACTIONS                   │
│   ───────────                  ──────────────                   │
│                                                                 │
│   ┌──────────────┐             ┌──────────────────────────────┐ │
│   │ countdown.html│            │ .github/workflows/renew.yml  │ │
│   │              │             │                              │ │
│   │  ┌────────┐  │   POST     │  workflow_dispatch:           │ │
│   │  │ Timer  │  │   ─────►   │    inputs:                    │ │
│   │  │ 27 min │  │            │      renewal_code: ***        │ │
│   │  └────────┘  │            │                              │ │
│   │              │             │  1. Validate code vs secret  │ │
│   │  Enter code: │             │  2. If valid:                │ │
│   │  ┌────────┐  │             │     - Reset timer            │ │
│   │  │ ****   │──┼──────────► │     - Set state to OK        │ │
│   │  └────────┘  │             │     - Commit state.json      │ │
│   │              │             │  3. Rebuild site             │ │
│   └──────────────┘             └──────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Renewal Code Validation

**Option A: GitHub Secret (Recommended)**
```yaml
# .github/workflows/renew.yml
- name: Validate renewal code
  env:
    RENEWAL_SECRET: ${{ secrets.RENEWAL_SECRET }}
  run: |
    if [ "${{ inputs.renewal_code }}" != "$RENEWAL_SECRET" ]; then
      echo "Invalid renewal code"
      exit 1
    fi
```

**Option B: Hashed code in state**
```python
# In state.json
"renewal": {
    "code_hash": "sha256:abc123...",  # Hash of valid code
    "last_renewal_iso": "..."
}
```

### Public Countdown Page

Generate `countdown.html` with:
- Live countdown timer (JavaScript)
- Current stage indicator
- Code entry form (submits to workflow_dispatch via GitHub API)
- Status history

```html
<!-- public/countdown.html -->
<div class="countdown-display">
  <h2>Time Remaining</h2>
  <div id="timer">--:--:--</div>
  
  <form id="renew-form">
    <input type="password" id="code" placeholder="Enter renewal code">
    <button type="submit">Renew</button>
  </form>
</div>

<script>
  // Fetch deadline from state API or embedded data
  // Countdown logic
  // Submit to GitHub workflow_dispatch
</script>
```

### Files to Create/Modify
- `.github/workflows/renew.yml` — Renewal workflow
- `src/site/generator.py` — Generate countdown.html
- `docs/RENEWAL.md` — Document renewal process

---

## ⚙️ Component 3: Configuration Validation

### Problem
When adapters are used but not configured, errors are silent or unclear.

### Solution

**Configuration validator** that checks all required settings:

```python
# src/config/validator.py

class ConfigValidator:
    """Validate adapter and system configuration."""
    
    def validate_adapter(self, adapter_name: str) -> ConfigStatus:
        """Check if adapter is properly configured."""
        checks = {
            "email": self._check_email_config,
            "sms": self._check_sms_config,
            "github_surface": self._check_github_config,
            "webhook": self._check_webhook_config,
            "persistence_api": self._check_persistence_config,
        }
        return checks.get(adapter_name, self._check_unknown)()
    
    def _check_email_config(self) -> ConfigStatus:
        api_key = os.environ.get("RESEND_API_KEY")
        from_email = os.environ.get("RESEND_FROM_EMAIL")
        
        if not api_key:
            return ConfigStatus(
                configured=False,
                missing=["RESEND_API_KEY"],
                guidance="Get API key from https://resend.com/api-keys"
            )
        if not from_email:
            return ConfigStatus(
                configured=False,
                missing=["RESEND_FROM_EMAIL"],
                guidance="Set verified sender email from Resend dashboard"
            )
        return ConfigStatus(configured=True)
```

### Logging Levels

```
┌─────────────────────────────────────────────────────────────────┐
│                    ADAPTER STATUS LOGGING                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ 1. At startup (AdapterRegistry initialization):                 │
│    INFO:  "email adapter: CONFIGURED (Resend)"                 │
│    WARN:  "sms adapter: NOT CONFIGURED (TWILIO_SID missing)"   │
│    DEBUG: "x adapter: MOCK MODE (no credentials)"              │
│                                                                 │
│ 2. On action attempt:                                           │
│    INFO:  "Executing remind_sms via sms adapter"               │
│    WARN:  "sms adapter not configured, skipping remind_sms"    │
│    ERROR: "sms adapter failed: timeout after 30s"              │
│                                                                 │
│ 3. In tick summary:                                             │
│    "Tick T-xxx complete: 3 actions executed, 1 skipped, 0 failed"
│    "Skipped actions: remind_sms (adapter not configured)"       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Files to Create/Modify
- `src/config/validator.py` — Configuration validators
- `src/config/status.py` — Status models
- `src/adapters/registry.py` — Log adapter status on registration
- `tests/test_config.py` — Test configuration validation

---

## 📊 Component 4: Enhanced Adapter Logging

### Current vs Desired

| Scenario | Current | Desired |
|----------|---------|---------|
| Adapter not configured | Silent skip | WARN with guidance |
| Adapter configured | INFO | INFO with details |
| Adapter execution | Basic log | Structured JSON |
| Adapter failure | Basic error | Error + retry info |

### Implementation

```python
# In adapter execution
def execute_with_logging(adapter, context):
    config_status = validator.validate_adapter(adapter.name)
    
    if not config_status.configured:
        logger.warning(
            f"Adapter '{adapter.name}' not configured",
            extra={
                "action_id": context.action.id,
                "missing": config_status.missing,
                "guidance": config_status.guidance,
            }
        )
        return Receipt.skipped(
            adapter=adapter.name,
            action_id=context.action.id,
            reason="not_configured",
            guidance=config_status.guidance,
        )
    
    logger.info(
        f"Executing {context.action.id} via {adapter.name}",
        extra={"channel": context.action.channel}
    )
    
    return adapter.execute(context)
```

---

## 📝 Component 5: User Guidance

### Setup Wizard (`init` command)

```bash
$ python -m src.main init

🔧 Continuity Orchestrator Setup
================================

1. Project name: my-continuity-system
2. Renewal period (hours): 48
3. Configure adapters:
   - Email (Resend)? [y/N]: y
     → Set RESEND_API_KEY in GitHub Secrets
   - SMS (Twilio)? [y/N]: n
   - GitHub Pages? [Y/n]: y

✅ Created:
   - state/current.json (initialized)
   - policy/ (copied defaults)
   - content/articles/example.json
   - .github/workflows/ (configured)

📖 Next steps:
   1. Set secrets in GitHub: Settings > Secrets
   2. Create your first article: content/articles/my_article.json
   3. Push to GitHub to start the countdown
```

### Editor.js Authoring Guide

Create `docs/AUTHORING.md`:
- How to structure articles
- Block type reference
- Inline formatting guide
- Example templates for each stage
- Best practices (no external images, etc.)

### Configuration Reference

Create `docs/CONFIGURATION.md`:
- All environment variables
- All GitHub Secrets needed
- Adapter-specific setup guides
- Troubleshooting common issues

---

## 📅 Implementation Order

### Phase 1: Core Flows (Priority)
| Task | Effort | Files |
|------|--------|-------|
| 1. Content manifest & stage filtering | 2h | manifest.py, generator.py |
| 2. Renewal workflow | 3h | renew.yml, CLI command |
| 3. Countdown page with JS timer | 2h | generator.py |

### Phase 2: Configuration & Logging
| Task | Effort | Files |
|------|--------|-------|
| 4. Configuration validator | 2h | config/validator.py |
| 5. Enhanced adapter logging | 1h | registry.py |
| 6. Tick summary with skip reasons | 1h | tick.py |

### Phase 3: User Experience
| Task | Effort | Files |
|------|--------|-------|
| 7. Init command / setup wizard | 3h | main.py, templates/ |
| 8. AUTHORING.md guide | 1h | docs/ |
| 9. CONFIGURATION.md reference | 1h | docs/ |

### Phase 4: Additional Adapters
| Task | Effort | Files |
|------|--------|-------|
| 10. SMS/Twilio adapter | 2h | adapters/sms_twilio.py |
| 11. X/Twitter adapter | 4h | adapters/x_twitter.py |
| 12. Reddit adapter | 4h | adapters/reddit.py |

---

## 🔢 Data Flow Summary

```
                    ┌─────────────────┐
                    │   manifest.yaml │
                    │   (visibility)  │
                    └────────┬────────┘
                             │
                             ▼
┌──────────┐         ┌──────────────┐         ┌─────────────┐
│ Editor.js│  ────►  │ content/*.json│  ────►  │ Site Gen    │
│  Author  │         │ (articles)   │         │ (filtered)  │
└──────────┘         └──────────────┘         └──────┬──────┘
                                                     │
                                                     ▼
                                              ┌──────────────┐
                                              │  public/     │
                                              │  articles/   │
                                              │  countdown.  │
                                              └──────┬───────┘
                                                     │
                    ┌─────────────────┐              │
                    │ workflow        │◄─────────────┘
                    │ renew.yml       │     (code entry)
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ state.json      │
                    │ (reset timer)   │
                    └─────────────────┘
```

---

## ✅ Success Criteria

1. Articles only appear when their stage is reached
2. Renewal code extends deadline via secure workflow
3. Clear logs for every adapter state
4. Users can bootstrap a new instance with `init`
5. Comprehensive docs for authoring and configuration
