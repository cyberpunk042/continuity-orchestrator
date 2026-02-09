/**
 * Sentinel Types — Shared interfaces for state, signals, config, and decisions.
 */

// ─── What the engine pushes after every tick ───────────────────────
export interface SentinelState {
    /** ISO timestamp of last tick completion */
    lastTickAt: string;
    /** Countdown deadline (timer.deadline_iso) */
    deadline: string;
    /** Current escalation stage ("OK", "REMIND_1", ...) */
    stage: string;
    /** When current stage was entered (escalation.state_entered_at_iso) */
    stageEnteredAt: string;
    /** Whether the last tick was a renewal */
    renewedThisTick: boolean;
    /** Last renewal timestamp (renewal.last_renewal_iso) */
    lastRenewalAt: string;
    /** Did the last tick change the escalation state? */
    stateChanged: boolean;
    /** Monotonic version counter for conflict detection */
    version: number;
}

// ─── Signals pushed by renew/release actions ──────────────────────
export interface Signal {
    type: "renewal" | "release" | "urgent";
    /** ISO timestamp of when the signal was generated */
    at: string;
    /** Random nonce to deduplicate */
    nonce: string;
}

// ─── Static config written once by the CLI wizard ─────────────────
export interface SentinelConfig {
    /** Primary GitHub repo ("owner/repo") */
    repo: string;
    /** Mirror repo for failover ("owner/mirror-repo"), optional */
    mirrorRepo?: string;
    /** Which workflow file to dispatch ("cron.yml") */
    workflowFile: string;
    /** Normal tick cadence in minutes (default: 15) */
    defaultCadenceMinutes: number;
    /** How early to dispatch before a stage threshold (default: 10) */
    urgencyWindowMinutes: number;
    /** Stage escalation thresholds derived from policy/rules.yaml */
    thresholds: Threshold[];
    /** Minimum minutes between dispatches (default: 5) */
    maxBackoffMinutes: number;
}

export interface Threshold {
    /** Target escalation stage ("REMIND_1", "REMIND_2", ...) */
    stage: string;
    /** Minutes before deadline when this stage triggers */
    minutesBefore: number;
}

// ─── Decision output ──────────────────────────────────────────────
export interface Decision {
    dispatch: boolean;
    reason: string;
}

// ─── Observability log ────────────────────────────────────────────
export interface DecisionLog {
    at: string;
    dispatch: boolean;
    reason: string;
    state: SentinelState | null;
    signal: Signal | null;
    nextDueAt: string | null;
}

// ─── Worker environment bindings ──────────────────────────────────
export interface Env {
    SENTINEL_KV: KVNamespace;
    SENTINEL_TOKEN: string;
    GITHUB_TOKEN: string;
    ENVIRONMENT: string;
}
