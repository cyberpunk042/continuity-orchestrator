# Minimal Example

The absolute minimum to run Continuity Orchestrator.

## Files

```
minimal/
├── README.md          # This file
├── policy/
│   ├── rules.yaml     # Just 3 essential rules
│   └── states.yaml    # 4 states
└── .env.example       # Environment template
```

## Setup

```bash
# Copy this example to your project
cp -r examples/minimal/* .

# Set your email
export RESEND_API_KEY=re_your_key
export OPERATOR_EMAIL=you@example.com

# Initialize
python -m src.main init --project minimal-test

# Run
python -m src.main tick
```

## What This Does

1. **Timer** — 48-hour countdown
2. **Warning** — Email at 24h remaining
3. **Critical** — Email at 6h remaining  
4. **Final** — Email when deadline passes

That's it. No social publishing, no webhooks, no complexity.
