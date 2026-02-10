/**
 * Sentinel Decision Logic — Pure function that determines whether to dispatch.
 *
 * This is the core of the sentinel.  It takes the current state, any pending
 * signals, the config, and the current time, and returns a boolean + reason.
 *
 * Design: every rule is checked top-to-bottom.  First match wins.
 * The order encodes priority:
 *   signals > debounce > terminal > bootstrap > overdue > threshold > cadence > idle
 *
 * Key design decisions:
 *   - Signals BYPASS backoff — a user renewal must be processed immediately
 *   - Terminal FULL blocks cadence dispatch but NOT signal processing
 *   - Stale engine (no tick in 2× cadence) triggers aggressive dispatch
 *   - Overdue dispatch respects backoff to avoid spamming Actions minutes
 */

import type { Decision, SentinelConfig, SentinelState, Signal } from "./types";

/**
 * Determine whether the sentinel should dispatch a workflow right now.
 *
 * @param state  - Latest engine state (null if never received)
 * @param signal - Pending signal from renew/release (null if none)
 * @param config - Sentinel configuration (thresholds, cadence, etc.)
 * @param now    - Current time
 * @param lastDispatchAt - ISO timestamp of last dispatch (for debounce)
 * @param prevReason - Reason from the last saved decision (for bootstrap loop prevention)
 */
export function shouldDispatch(
    state: SentinelState | null,
    signal: Signal | null,
    config: SentinelConfig,
    now: Date,
    lastDispatchAt: string | null,
    prevReason: string | null = null,
): Decision {

    // ── 0. Fresh signal ALWAYS dispatches (bypasses backoff) ──────
    //    A user renewal/release/urgent signal is time-critical.
    //    The user is actively waiting — don't make them wait for backoff.
    if (signal && state && signal.at > state.lastTickAt) {
        return { dispatch: true, reason: `signal:${signal.type}` };
    }
    // Signal without state: also dispatch to process it
    if (signal && !state) {
        return { dispatch: true, reason: `signal:${signal.type}` };
    }

    // ── 1. Debounce: don't dispatch if we just did ────────────────
    //    (This is checked AFTER signals — signals bypass backoff)
    if (lastDispatchAt) {
        const sinceLast = (now.getTime() - new Date(lastDispatchAt).getTime()) / 60_000;
        if (sinceLast < config.maxBackoffMinutes) {
            return { dispatch: false, reason: `backoff:${Math.round(sinceLast)}m/${config.maxBackoffMinutes}m` };
        }
    }

    // ── 2. Terminal state: FULL = nothing further to do ────────────
    //    Checked AFTER signals so a renewal at FULL can still be processed.
    if (state?.stage === "FULL") {
        return { dispatch: false, reason: "terminal:FULL" };
    }

    // ── 3. Bootstrap: no state received yet ─────────────────────────
    //    Dispatch ONCE to kick-start the engine.  If we already dispatched
    //    for "bootstrap" (even if the lock expired), don't keep spamming —
    //    the engine needs to push state after a successful tick.
    if (!state) {
        if (lastDispatchAt || prevReason === "bootstrap") {
            return { dispatch: false, reason: "bootstrap:waiting" };
        }
        return { dispatch: true, reason: "bootstrap" };
    }

    // ── 4. Stale engine: no tick in 2× cadence period ────────────
    //    If the engine hasn't reported in a long time, something is wrong.
    //    Dispatch to try to revive it. This acts as a "heartbeat" check.
    const lastTick = new Date(state.lastTickAt);
    const minutesSinceLastTick = (now.getTime() - lastTick.getTime()) / 60_000;
    const staleCutoff = config.defaultCadenceMinutes * 2;
    if (minutesSinceLastTick >= staleCutoff) {
        return { dispatch: true, reason: `stale:${Math.round(minutesSinceLastTick)}m` };
    }

    // ── 5. Overdue: deadline has passed, engine hasn't caught up ──
    const deadline = new Date(state.deadline);
    const minutesToDeadline = (deadline.getTime() - now.getTime()) / 60_000;

    if (minutesToDeadline <= 0) {
        return { dispatch: true, reason: "overdue" };
    }

    // ── 6. Stage threshold approaching ────────────────────────────
    //    Check if we're within urgencyWindow of a threshold that
    //    hasn't been reached yet.  Thresholds should be sorted
    //    descending by minutesBefore (earliest stage first).
    for (const t of config.thresholds) {
        const triggerAt = t.minutesBefore + config.urgencyWindowMinutes;
        if (minutesToDeadline <= triggerAt && !hasReachedStage(state.stage, t.stage)) {
            return { dispatch: true, reason: `stage_near:${t.stage}` };
        }
    }

    // ── 7. Normal cadence ─────────────────────────────────────────
    if (minutesSinceLastTick >= config.defaultCadenceMinutes) {
        return { dispatch: true, reason: "cadence" };
    }

    // ── 8. Idle ───────────────────────────────────────────────────
    return { dispatch: false, reason: "idle" };
}


/**
 * Compute when the next dispatch would be due (for observability).
 */
export function computeNextDueAt(
    state: SentinelState | null,
    config: SentinelConfig,
): string | null {
    if (!state) return null;

    const lastTick = new Date(state.lastTickAt);
    const nextCadence = new Date(lastTick.getTime() + config.defaultCadenceMinutes * 60_000);

    // Also check the earliest threshold that hasn't been reached yet
    const deadline = new Date(state.deadline);
    let earliestThreshold: Date | null = null;

    for (const t of config.thresholds) {
        if (!hasReachedStage(state.stage, t.stage)) {
            const thresholdTime = new Date(deadline.getTime() - (t.minutesBefore + config.urgencyWindowMinutes) * 60_000);
            if (!earliestThreshold || thresholdTime < earliestThreshold) {
                earliestThreshold = thresholdTime;
            }
        }
    }

    // Return whichever comes first
    if (earliestThreshold && earliestThreshold < nextCadence) {
        return earliestThreshold.toISOString();
    }

    return nextCadence.toISOString();
}


// ─── Stage ordering for "has reached" checks ──────────────────────
const STAGE_ORDER: Record<string, number> = {
    "OK": 0,
    "REMIND_1": 1,
    "REMIND_2": 2,
    "PRE_RELEASE": 3,
    "PARTIAL": 4,
    "FULL": 5,
};

/**
 * Check if the current stage is at or past the target stage.
 */
function hasReachedStage(current: string, target: string): boolean {
    const currentOrder = STAGE_ORDER[current] ?? -1;
    const targetOrder = STAGE_ORDER[target] ?? -1;
    return currentOrder >= targetOrder;
}
