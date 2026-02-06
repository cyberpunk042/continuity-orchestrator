# Manual Release Trigger

This document explains the manual release trigger feature — the ability to immediately initiate disclosure before the countdown expires.

---

## Overview

The manual release trigger allows you to:

1. **Trigger immediate disclosure** — Start the disclosure process without waiting for the deadline
2. **Add an optional delay** — Give yourself a grace period to cancel
3. **Control scope** — Release everything or just update the site

This is useful for:
- Emergency situations where you need to disclose now
- Planned releases where you've decided the time is right
- Testing the full disclosure flow

---

## How It Works

### The Flow

```
┌─────────────────────────────────────────────────────────────┐
│ You enter RELEASE_SECRET via dashboard or workflow          │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ State file updated:                                          │
│   release.triggered = true                                   │
│   release.execute_after_iso = [now + delay]                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ Site rebuilds immediately showing "DELAYED" status          │
│ (if delay > 0)                                               │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ Next tick checks: Is now >= execute_after_iso?               │
│   YES → Execute FULL stage actions (email, SMS, publish)    │
│   NO  → Wait for next tick                                  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ Site shows FULL disclosure state                             │
│ All configured integrations execute                          │
└─────────────────────────────────────────────────────────────┘
```

### Delayed Release

When you trigger with a delay:

1. **Immediately:** Site updates to show "DELAYED" status
2. **During delay:** You can cancel by renewing
3. **After delay:** Next tick executes the release

This gives you a "cool-off" period to reconsider.

---

## Triggering a Release

### Method 1: GitHub Actions Workflow

1. Go to **Actions** → **Renew Deadline**
2. Click **Run workflow**
3. Enter your `RELEASE_SECRET` as the renewal code
4. Optionally set delay minutes
5. Click **Run workflow**

What happens:
- State updates with `release.triggered = true`
- Site rebuilds with "DELAYED" indicator
- Next tick will execute if delay has passed

### Method 2: Dashboard (countdown.html)

If configured:
1. Navigate to your dashboard at `/countdown.html`
2. Click "Emergency Release" or similar
3. Enter your `RELEASE_SECRET`
4. Confirm

### Method 3: CLI

```bash
# Trigger with 60-minute delay
python -m src.main trigger-release --stage FULL --delay 60

# Immediate trigger (no delay)
python -m src.main trigger-release --stage FULL --delay 0

# Trigger only site update (no integrations)
python -m src.main trigger-release --stage FULL --delay 60 --delay-scope site_only
```

---

## Canceling a Delayed Release

If you triggered a release with a delay and want to cancel:

### Before the Delay Expires

**Renew the deadline.** This clears the release trigger:

```bash
python -m src.main renew --hours 48
```

Or via the dashboard/workflow with your `RENEWAL_SECRET`.

The renewal:
1. Clears `release.triggered`
2. Resets state to OK
3. Sets new deadline
4. Rebuilds site

### After the Delay Expires

Once the tick has executed, **disclosure is final**. Actions already taken cannot be undone.

---

## Configuration

### Release Delay Settings

In `.env`:

```bash
# Default delay when triggering release (minutes)
RELEASE_DELAY_MINUTES=60

# What to delay: "full" or "site_only"
RELEASE_DELAY_SCOPE=full
```

Options:
- `full` — Delay all actions (email, SMS, social, publish)
- `site_only` — Site updates immediately, other actions wait

### The RELEASE_SECRET

Generate a strong secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Store this:
- ✅ Password manager
- ✅ Secure backup location
- ❌ Never in the repository
- ❌ Never in logs

---

## State Fields

When a release is triggered, these fields are set:

```json
{
  "release": {
    "triggered": true,
    "trigger_time_iso": "2026-02-06T15:30:00Z",
    "execute_after_iso": "2026-02-06T16:30:00Z",
    "target_stage": "FULL",
    "client_token": "abc123..."
  }
}
```

| Field | Description |
|-------|-------------|
| `triggered` | Whether release has been triggered |
| `trigger_time_iso` | When the trigger was initiated |
| `execute_after_iso` | When actions should execute (after delay) |
| `target_stage` | Which stage to transition to |
| `client_token` | Token returned to caller for verification |

---

## Site Behavior During Delay

When `release.triggered = true` but delay hasn't passed:

### Dashboard Shows

- **Stage badge:** "DELAYED"
- **Countdown timer:** Shows "⏸️ RELEASE DELAYED"
- **Deadline:** Shows strike-through or "DELAYED"
- **Status message:** Indicates pending release

### status.json Contains

```json
{
  "stage": "DELAYED",
  "release_triggered": true,
  "deadline": "...",
  "time_to_deadline": 0
}
```

This allows client-side JavaScript to show appropriate UI.

---

## Audit Trail

All release triggers are logged:

```json
// In audit/ledger.ndjson
{
  "event_type": "release_triggered",
  "timestamp": "2026-02-06T15:30:00Z",
  "tick_id": "R-20260206T153000-RELEASE",
  "target_stage": "FULL",
  "delay_minutes": 60,
  "execute_after": "2026-02-06T16:30:00Z"
}
```

When executed:

```json
{
  "event_type": "state_transition",
  "from_state": "OK",
  "to_state": "FULL",
  "rule_id": "MANUAL_RELEASE"
}
```

---

## Security Considerations

### Protect the RELEASE_SECRET

This code has significant power:
- Immediately triggers disclosure (with optional delay)
- Cannot be undone once executed

**Best practices:**
- Use a different code than RENEWAL_SECRET
- Store in password manager only
- Don't share unless absolutely necessary
- Rotate if suspected compromise

### Revocation

If RELEASE_SECRET is compromised:

1. **Immediately regenerate:**
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. **Update GitHub Secret:**
   - Settings → Secrets → Update `RELEASE_SECRET`

3. **Check state:**
   - Verify `release.triggered` is not set
   - If set, check `execute_after_iso` — you may have time to renew

4. **Review audit log:**
   ```bash
   cat audit/ledger.ndjson | grep release
   ```

---

## Troubleshooting

### Release Triggered But Nothing Happened

1. **Check delay:** Is `execute_after_iso` still in the future?
2. **Wait for tick:** Cron runs every 30 minutes
3. **Check state:** Is `release.triggered` actually true?
4. **Check Actions log:** Look for errors in the tick

### Site Shows DELAYED But State is OK

The site may be stale. Trigger a site rebuild:
- Run the cron workflow manually
- Or locally: `python -m src.main build-site`

### Can't Cancel — Renewal Doesn't Work

1. Verify you're using `RENEWAL_SECRET` (not `RELEASE_SECRET`)
2. Check secret matches exactly (no spaces)
3. Run renewal locally if Actions workflow fails

---

## Examples

### Emergency Disclosure (Immediate)

```bash
# Trigger now, no delay
python -m src.main trigger-release --stage FULL --delay 0
```

Result: Next tick executes all FULL stage actions.

### Planned Release (With Safety Window)

```bash
# Trigger with 2-hour delay
python -m src.main trigger-release --stage FULL --delay 120
```

Result: 
- Site immediately shows "DELAYED"
- You have 2 hours to cancel via renewal
- After 2 hours, next tick executes

### Site-Only Update

```bash
# Only update site, don't send notifications
python -m src.main trigger-release --stage FULL --delay 0 --delay-scope site_only
```

Result: Site publishes, but email/SMS/social wait.

---

## Related Documentation

- [SECURITY.md](../SECURITY.md) — Security best practices
- [DISCLAIMER.md](../DISCLAIMER.md) — Important warnings
- [QUICKSTART.md](QUICKSTART.md) — Getting started
- [ARCHITECTURE.md](ARCHITECTURE.md) — How the engine works

---

*Use this power responsibly.*
