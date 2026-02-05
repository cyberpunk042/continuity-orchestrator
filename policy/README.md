# Policy Configuration

This directory contains the rules and plans that drive the orchestrator.

## Files

| File | Description |
|------|-------------|
| `rules.yaml` | Escalation rules — when to transition between states |
| `states.yaml` | State definitions — OK, WARNING, CRITICAL, FINAL |
| `plans/` | Action plans — what to do at each state |

## Quick Reference

### rules.yaml

```yaml
rules:
  - id: R10_WARNING
    description: "Enter warning at 24h before deadline"
    when:
      - time_to_deadline_minutes <= 1440
      - escalation_state == "OK"
    then:
      transition_to: WARNING
```

### Conditions Available

| Condition | Example |
|-----------|---------|
| `time_to_deadline_minutes` | `<= 1440` (24 hours) |
| `overdue_minutes` | `> 0` |
| `escalation_state` | `== "OK"` |
| `renewal_count` | `< 3` |
| `armed` | `== true` |

### Action Types

| Type | Description |
|------|-------------|
| `email` | Send email via Resend |
| `sms` | Send SMS via Twilio |
| `x_post` | Post to X (Twitter) |
| `reddit_post` | Post to Reddit |
| `webhook` | HTTP POST to URL |
| `github_surface` | Publish to GitHub Pages |

## Learn More

See [docs/CONFIGURATION.md](../docs/CONFIGURATION.md) for complete reference.
