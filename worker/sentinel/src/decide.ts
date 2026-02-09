/**
 * Sentinel Decision Logic — Pure function that determines whether to dispatch.
 *
 * This is the core of the sentinel.  It takes the current state, any pending
 * signals, the config, and the current time, and returns a boolean + reason.
 *
 * Design: every rule is checked top-to-bottom.  First match wins.
 * The order encodes priority: signals > urgency > overdue > cadence > idle.
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
 */
export function shouldDispatch(
    state: SentinelState | null,
    signal: Signal | null,
    config: SentinelConfig,
    now: Date,
    lastDispatchAt: string | null,
): Decision {

    // ── 0. Terminal state: FULL = nothing further to do ────────────
    if (state?.stage === "FULL") {
        return { dispatch: false, reason: "terminal:FULL" };
    }

    // ── 1. Debounce: don't dispatch if we just did ────────────────
    if (lastDispatchAt) {
        const sinceLast = (now.getTime() - new Date(lastDispatchAt).getTime()) / 60_000;
        if (sinceLast < config.maxBackoffMinutes) {
            return { dispatch: false, reason: `backoff:${Math.round(sinceLast)}m/${config.maxBackoffMinutes}m` };
        }
    }

    // ── 2. Bootstrap: no state received yet → dispatch immediately ─
    if (!state) {
        return { dispatch: true, reason: "bootstrap" };
    }

    // ── 3. Fresh signal (renewal, release, urgent) ────────────────
    if (signal && signal.at > state.lastTickAt) {
        return { dispatch: true, reason: `signal:${signal.type}` };
    }

    // ── 4. Overdue: deadline has passed, engine hasn't caught up ──
    const deadline = new Date(state.deadline);
    const minutesToDeadline = (deadline.getTime() - now.getTime()) / 60_000;

    if (minutesToDeadline <= 0) {
        return { dispatch: true, reason: "overdue" };
    }

    // ── 5. Stage threshold approaching ────────────────────────────
    //    Check if we're within urgencyWindow of a threshold that
    //    hasn't been reached yet.  Thresholds should be sorted
    //    descending by minutesBefore (earliest stage first).
    for (const t of config.thresholds) {
        const triggerAt = t.minutesBefore + config.urgencyWindowMinutes;
        if (minutesToDeadline <= triggerAt && !hasReachedStage(state.stage, t.stage)) {
            return { dispatch: true, reason: `stage_near:${t.stage}` };
        }
    }

    // ── 6. Normal cadence ─────────────────────────────────────────
    const lastTick = new Date(state.lastTickAt);
    const minutesSinceLastTick = (now.getTime() - lastTick.getTime()) / 60_000;
    if (minutesSinceLastTick >= config.defaultCadenceMinutes) {
        return { dispatch: true, reason: "cadence" };
    }

    // ── 7. Idle ───────────────────────────────────────────────────
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
