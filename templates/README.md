# Templates

Message templates for notifications and published content.

## Structure

```
templates/
├── emails/           # Email templates
│   ├── reminder.md
│   ├── urgent.md
│   └── final.md
│
├── sms/              # SMS templates (short)
│   └── urgent.txt
│
├── social/           # Social media posts
│   ├── x_post.md
│   └── reddit.md
│
└── articles/         # Long-form content
    └── release.md
```

## Template Variables

All templates support these variables:

| Variable | Description |
|----------|-------------|
| `{{project}}` | Project name |
| `{{deadline}}` | Deadline timestamp |
| `{{time_remaining}}` | Human-readable time left |
| `{{operator_email}}` | Operator's email |
| `{{state}}` | Current escalation state |
| `{{renewal_url}}` | URL to renew (if enabled) |

## Example Template

```markdown
# Continuity Reminder

Hi,

Your countdown for **{{project}}** has {{time_remaining}} remaining.

**Deadline:** {{deadline}}
**Current State:** {{state}}

---
This is an automated message from Continuity Orchestrator.
```

## Notes

- Email templates use Markdown (converted to HTML)
- SMS templates should be under 160 characters
- Social templates should respect platform limits
