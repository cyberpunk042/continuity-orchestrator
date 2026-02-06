# Templates

Message and site templates for notifications and the public dashboard.

---

## Directory Structure

```
templates/
├── operator/          # Email/SMS templates for you
│   ├── reminder_basic.md
│   ├── reminder_strong.md
│   └── reminder_sms.txt
│
├── custodians/        # Templates for trusted contacts
│   └── ...
│
├── html/              # Website templates
│   ├── base.html      # Shared header/footer
│   ├── index.html     # Dashboard homepage
│   ├── countdown.html # Live countdown timer
│   ├── status.html    # Status display
│   └── article.html   # Article page template
│
├── css/               # Stylesheets
│   └── ...
│
├── articles/          # Article layout templates
│   └── ...
│
└── public/            # Static assets
    └── ...
```

---

## Operator Templates

Used for email and SMS notifications to you:

**`operator/reminder_basic.md`** — First reminder email  
**`operator/reminder_strong.md`** — Urgent reminder email  
**`operator/reminder_sms.txt`** — SMS message (keep under 160 chars)

---

## Template Variables

All templates can use these placeholders:

| Variable | Description |
|----------|-------------|
| `{{ project }}` | Your project name |
| `{{ deadline }}` | Deadline timestamp |
| `{{ time_to_deadline }}` | Minutes until deadline |
| `{{ stage }}` | Current stage (OK, WARNING, etc.) |
| `{{ operator_email }}` | Your email |

---

## Customizing

### Change email wording

Edit `templates/operator/reminder_basic.md`:

```markdown
# Reminder: {{ project }}

Your deadline is approaching.

**Time remaining:** {{ time_to_deadline }} minutes
```

### Change site appearance

Edit `templates/html/` and `templates/css/` files.

---

## Notes

- Email templates use Markdown (converted to HTML)
- SMS must be under 160 characters
- HTML templates use Jinja2 syntax
