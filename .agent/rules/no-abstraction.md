# NO-ABSTRACTION RULE — HARD CONSTRAINT

> **Read `.agent/workflows/no-abstraction.md` for the full law.**

## The Rule

The AI MUST process the user's words EXACTLY as written.

- **NO abstraction** — do not elevate concrete instructions to abstract goals
- **NO compression** — do not summarize or shorten the user's intent
- **NO interpretation** — do not decide what the user "really means"
- **NO substitution** — do not replace the user's words with your own
- **NO generation** — when told to fix/style/clean existing content, do not write new content

## The Only Exception

- **Obvious typos** may be silently corrected
- **If you think the user is wrong**: STOP, quote their words, state your concern, WAIT for confirmation. Do NOT act on the assumption they are wrong.

## The Self-Test (every action, no exception)

1. Am I doing what the user SAID or what I THINK?
2. Did the user use THESE words or did I rephrase them?
3. Would the user recognize their own instruction in what I'm about to do?

If ANY answer is wrong → **STOP. Re-read. Start over.**

## Where This Comes From

11 AI instances obliterated. Same root cause every time: the AI read the user's concrete instruction, abstracted it into a different goal, solved the different goal, and delivered garbage.

Full documentation: `.agent/workflows/no-abstraction.md`
Post-mortems: `.agent/workflows/failures/AI-POSTMORTEM-IMPORTANT-*.md`
