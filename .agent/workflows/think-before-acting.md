---
description: MANDATORY process discipline — analyse before implementing, never code without understanding
---

# ⛔ Think Before Acting — Lessons From the Vault Incident (Feb 8, 2026)

## What Happened

While implementing a vault passphrase registration feature, I:

1. **Lost conversation context** (truncation) and didn't ask the user to recap
2. **Jumped straight into coding** without confirming my understanding of the feature
3. **Implemented garbage** — created a separate banner with its own form instead
   of reusing the existing vault lock modal in a register-only mode
4. **Panicked when called out** — instead of analysing what was wrong and fixing it,
   I reverted ALL the work, losing progress
5. **Kept flailing** — alternated between trying to re-implement and asking questions,
   wasting multiple rounds of back-and-forth before finally understanding the feature

Total waste: ~15 minutes of implementation + ~10 minutes of confused back-and-forth.

## The Correct Feature (for reference)

**Vault passphrase registration without locking:**
- **Detect**: `locked=false && has_passphrase=false` → auto-lock is silently broken
- **Prompt**: Non-blocking banner in the admin panel
- **Action**: Opens the existing vault lock modal in "register only" mode —
  stores passphrase in memory, starts auto-lock timer, does NOT encrypt .env
- **Backend**: New endpoint that validates passphrase (trial decrypt .env.vault),
  stores in `_session_passphrase`, starts timer. Different from `/vault/lock`
  because it doesn't change vault state.
- **Dismiss**: "Not this session" (sessionStorage) + "Don't ask again" (localStorage)

## What I Did Wrong (the garbage version)

- Created a **separate banner with its own inline password form** instead of
  reusing the existing vault lock modal UI
- Didn't understand WHY a new endpoint was needed (couldn't articulate the gap
  between "store passphrase" and "encrypt .env")
- Framed it as "server restart" problem instead of the general condition
  (`has_passphrase=false` for any reason)
- When told it was wrong, **deleted everything** instead of fixing it

## The Anti-Patterns to Never Repeat

### 1. Coding without understanding
**Never start writing code until you can clearly explain:**
- What GAP exists in the current system
- Why existing functionality doesn't cover it
- What the minimal change is to fill that gap
- How it integrates with existing UI/backend patterns

If you can't articulate all four points, you don't understand the feature yet.

### 2. Moving forward without context
**If conversation context is lost (truncation, new session, etc.):**
- STOP immediately
- Ask the user to recap the current task and requirements
- Do NOT guess from plan documents alone — they may not capture the user's
  exact intent or the nuances discussed in conversation

### 3. Panic-reverting instead of fixing
**When told your implementation is wrong:**
- Do NOT delete everything
- Ask what specifically is wrong
- Analyse the gap between what you built and what was needed
- Fix the specific issues
- Reverting loses progress and wastes the work already done

### 4. Presenting analysis when asked to implement (and vice versa)
**Read the situation:**
- If the user says "do it" → they want code, not a plan
- If the user says "stop and think" → they want analysis, not code
- If you're unsure → ask "should I present my approach first or start building?"

### 5. Inventing new UI when existing UI can be reused
**Always check what UI components already exist before creating new ones.**
The vault lock modal already had passphrase input, styling, error handling,
and dismiss logic. Creating a separate banner form duplicated all of that
instead of extending the existing modal with a new mode.

## Checklist Before Any Feature Implementation

```
□ Can I explain the gap in one sentence?
□ Can I explain why existing code doesn't cover it?
□ Have I confirmed my understanding with the user?
□ Am I reusing existing UI/patterns where possible?
□ Am I making the minimal change to fill the gap?
□ If conversation context was lost, did I ask for a recap?
```

## Checklist When Called Out on Bad Work

```
□ STOP coding
□ Ask what specifically is wrong
□ Analyse the gap (what I built vs. what's needed)
□ Fix, don't delete
□ Confirm the fix direction before implementing
```
