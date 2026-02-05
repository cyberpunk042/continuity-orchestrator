# Newsletter Example

Scheduled content publishing with countdown-based release.

## Use Case

You have content (articles, announcements, newsletters) that should be published on a schedule. The system:

1. Holds content until the deadline
2. Sends preview reminders before release
3. Publishes automatically when deadline passes

Unlike a deadman switch, this is **intended to execute**. The countdown is the publication schedule.

## Files

```
newsletter/
├── README.md              # This file
├── policy/
│   ├── rules.yaml         # Publishing rules
│   └── plans/
│       └── publish.yaml   # Publishing actions
├── templates/
│   └── preview.md         # Preview email template
└── content/
    ├── manifest.yaml      # Content registry
    └── articles/
        └── example.md     # Your article
```

## Setup

```bash
# Copy to your project root
cp -r examples/newsletter/* .

# Configure
cp .env.example .env
# Add your RESEND_API_KEY

# Initialize with publication deadline
python -m src.main init \
  --project "newsletter-jan" \
  --deadline-hours 72

# Add your content to content/articles/

# Arm
python -m src.main tick
```

## How It Works

1. **72h before**: Content is staged, you can preview
2. **24h before**: Preview email sent to you for final review
3. **Deadline**: 
   - Article published to GitHub Pages
   - Email sent to subscriber list
   - Optional: Post to X/Reddit

## Customizing

### Change the publication time

Edit `policy/rules.yaml`:
```yaml
# Publish immediately at deadline instead of waiting
- id: PUBLISH_ON_TIME
  when:
    - overdue_minutes >= 0
    - escalation_state != "PUBLISHED"
  then:
    transition_to: PUBLISHED
```

### Add social publishing

Edit `.env`:
```bash
X_API_KEY=xxx
X_API_SECRET=xxx
X_ACCESS_TOKEN=xxx
X_ACCESS_SECRET=xxx
```

Add to plan:
```yaml
PUBLISHED:
  - action: x_post
    template: newsletter_tweet
```

### Schedule multiple newsletters

Create separate state files or use different branches.
