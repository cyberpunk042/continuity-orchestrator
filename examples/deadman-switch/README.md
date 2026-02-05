# Deadman Switch Example

A classic deadman switch: if you don't check in, your designated contacts are notified.

## Use Case

You want to ensure that if something happens to you, important information reaches the right people. The system:

1. Runs on a 48-hour countdown
2. You renew it regularly (via web form, CLI, or API)
3. If you miss the renewal:
   - **24h left**: You get a reminder
   - **6h left**: You get an urgent alert + trusted contacts notified
   - **Deadline passed**: Full release — emails, document publishing, etc.

## Files

```
deadman-switch/
├── README.md              # This file
├── policy/
│   ├── rules.yaml         # Escalation rules
│   ├── states.yaml        # State definitions
│   └── plans/
│       └── default.yaml   # Actions per stage
├── templates/
│   ├── reminder.md        # 24h warning email
│   ├── urgent.md          # 6h urgent alert
│   └── final_notice.md    # Deadline passed
└── content/
    └── letter.md          # Your message to release
```

## Setup

```bash
# Copy to your project root
cp -r examples/deadman-switch/* .

# Configure credentials
cp .env.example .env
# Edit .env with your API keys

# Initialize
python -m src.main init \
  --project "my-deadman" \
  --operator-email "you@example.com" \
  --deadline-hours 48

# Arm the system
python -m src.main tick

# Check status
python -m src.main status
```

## Renewing

To reset the countdown:

```bash
# CLI
python -m src.main renew --secret YOUR_RENEWAL_CODE

# Or via the web interface (if enabled)
# POST /api/renew with your secret
```

## Security

- The renewal code is high-entropy (generated at init)
- Failed attempts trigger lockouts
- Reminder emails never contain the renewal link
- All actions are logged to the audit trail

## Customizing

### Change timing

Edit `policy/rules.yaml`:
```yaml
# Warning at 12 hours instead of 24
when:
  - time_to_deadline_minutes <= 720
```

### Add SMS

Add to `.env`:
```bash
TWILIO_ACCOUNT_SID=ACxxx
TWILIO_AUTH_TOKEN=xxx
TWILIO_FROM_NUMBER=+1234567890
```

Add to `policy/plans/default.yaml`:
```yaml
CRITICAL:
  - action: sms
    to: "{{operator_sms}}"
    template: urgent_sms
```

### Add trusted contacts

Edit `state/current.json`:
```json
"integrations": {
  "routing": {
    "custodian_emails": ["trusted@example.com", "another@example.com"]
  }
}
```
