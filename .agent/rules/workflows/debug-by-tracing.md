---
description: MANDATORY debug protocol — when the user shows you a comparison (working vs broken), TRACE the code path mechanically. Never guess.
---

# ⛔ Debug By Tracing — Never Guess

## When This Applies

When the user provides ANY of:
- A comparison: "X shows Y but Z shows W"
- A concrete error: "it says '⚠️ --' instead of 'MYSQL_DATABASE'"
- A screenshot showing wrong output next to correct output
- "Only X works, Y doesn't" (where X and Y go through similar code)

## The Protocol

### STEP 1: Identify the TWO outputs
- **Working output**: What shows correctly (e.g., "MYSQL_PASSWORD" appears)
- **Broken output**: What shows incorrectly (e.g., "--" appears instead of "MYSQL_DATABASE")

### STEP 2: Find the SHARED code path
Both outputs go through the same function/template. Find that function.

### STEP 3: Trace the WORKING case first
Follow the exact inputs that produce the correct output:
```
Function called with → args A, B, C → produces correct output
```
Write this out. Show the actual values.

### STEP 4: Trace the BROKEN case second
Follow the exact inputs that produce the wrong output:
```
Function called with → args X, Y, Z → produces broken output
```
Write this out. Show the actual values.

### STEP 5: Find the DIVERGENCE
Compare Step 3 and Step 4. The difference in inputs IS the bug.
Do NOT hypothesize. The divergence TELLS you the fix.

### STEP 6: Fix ONLY the divergence
The fix is making the broken case receive the same quality of inputs
as the working case. Nothing more.

## What You MUST NOT Do

- ❌ Skip tracing and jump to a hypothesis ("maybe it's a timing issue")
- ❌ Add guards/workarounds instead of fixing the root input
- ❌ Fix a symptom (guard against "--") instead of fixing WHY "--" arrives
- ❌ Propose multiple possible causes — there is ONE cause, and tracing finds it
- ❌ Look at unrelated code "for context"

## Why This Exists

On Feb 13, 2026, the user provided a precise comparison:
- `"⚠️ MYSQL_PASSWORD does not exist yet"` ← correct
- `"⚠️ -- does not exist yet"` ← broken

Instead of tracing both through `_envRowHtml` to see that one gets
`varName='${MYSQL_PASSWORD}'` and the other gets `varName=''` (because
`_defaultInjType` returned 'hardcoded'), the AI:
1. Guessed it was a cross-row detection timing issue
2. Added a "--" guard (symptom treatment)
3. Changed `_defaultInjType` for infra (still not tracing)

Three wrong fixes. The correct action was: trace both inputs through
`_envRowHtml`, see that `varName` is empty for one, ask WHY it's empty,
and fix the source of the empty value. Total: 5 minutes, 1 edit.

The AI wasted 15+ minutes and 3 broken edits because it GUESSED instead of TRACED.


MUST ACKNOWLEDGE: 
- ".agent/workflows/failures/AI-POSTMORTEM-IMPORTANT-1.md"
- ".agent/workflows/failures/AI-POSTMORTEM-IMPORTANT-2.md"
- ".agent/workflows/failures/AI-POSTMORTEM-IMPORTANT-3.md"
- ".agent/workflows/failures/AI-POSTMORTEM-IMPORTANT-4.md"
- ".agent/workflows/failures/AI-POSTMORTEM-IMPORTANT-5.md"
- ".agent/workflows/failures/AI-POSTMORTEM-IMPORTANT-6.md"
- ".agent/workflows/failures/AI-POSTMORTEM-IMPORTANT-7.md"
- ".agent/workflows/failures/AI-POSTMORTEM-IMPORTANT-8.md"
- ".agent/workflows/failures/AI-POSTMORTEM-IMPORTANT-9.md"
- ".agent/workflows/failures/AI-POSTMORTEM-IMPORTANT-10.md"
- ".agent/workflows/failures/AI-POSTMORTEM-IMPORTANT-11.md"