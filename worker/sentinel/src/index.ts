/**
 * Continuity Sentinel — Cloudflare Worker Entry Point
 *
 * Two handlers:
 *   fetch()     — HTTP API for receiving state/signals + serving status
 *   scheduled() — Cron trigger (every minute) that decides whether to dispatch
 *
 * KV Budget:
 *   Free tier = 1,000 writes/day, 100,000 reads/day.
 *   Cron runs 1,440 times/day (every minute).
 *   READS are cheap (~5/tick = 7,200/day — well within 100k).
 *   WRITES must be minimised:
 *     - last_decision: only on category change (not dynamic backoff values)
 *     - dispatch_lock: only on actual dispatch (~5-10/day)
 *     - state/signal/config: only on HTTP push (rare)
 *   Target: <50 writes/day in steady state.
 */

import { unauthorized, validateBearer } from "./auth";
import { computeNextDueAt, shouldDispatch } from "./decide";
import { dispatchWorkflow } from "./dispatch";
import type { DecisionLog, Env, SentinelConfig, SentinelState, Signal } from "./types";

// ─── CORS headers for dashboard access ──────────────────────────
const CORS_HEADERS: Record<string, string> = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

function json(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
        status,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
    });
}

/** Extract the category prefix from a reason string (e.g. "backoff" from "backoff:2m/5m"). */
function reasonCategory(reason: string): string {
    return reason.split(":")[0];
}

/** Safe KV put — catches quota errors and returns success/failure. */
async function kvPut(kv: KVNamespace, key: string, value: string, options?: KVNamespacePutOptions): Promise<boolean> {
    try {
        await kv.put(key, value, options);
        return true;
    } catch (err) {
        console.error(`[kv] ❌ PUT "${key}" failed:`, err);
        return false;
    }
}

/** Safe KV delete — catches quota errors. */
async function kvDelete(kv: KVNamespace, key: string): Promise<boolean> {
    try {
        await kv.delete(key);
        return true;
    } catch (err) {
        console.error(`[kv] ❌ DELETE "${key}" failed:`, err);
        return false;
    }
}

// ─── HTTP Handler ───────────────────────────────────────────────
async function handleFetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    console.log(`[http] ${method} ${path}`);

    // CORS preflight
    if (method === "OPTIONS") {
        return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    // ── Public endpoints ──────────────────────────────────────────

    if (method === "GET" && path === "/health") {
        return json({ ok: true, worker: "continuity-sentinel", ts: new Date().toISOString() });
    }

    if (method === "GET" && path === "/status") {
        return handleStatus(env);
    }

    // ── Protected endpoints ───────────────────────────────────────

    if (!validateBearer(request, env.SENTINEL_TOKEN)) {
        console.warn(`[http] 401 Unauthorized on ${method} ${path}`);
        return unauthorized();
    }

    if (method === "POST" && path === "/state") {
        return handlePostState(request, env);
    }

    if (method === "POST" && path === "/signal") {
        return handlePostSignal(request, env);
    }

    if (method === "POST" && path === "/config") {
        return handlePostConfig(request, env);
    }

    if (method === "POST" && path === "/reset") {
        return handlePostReset(request, env);
    }

    // ── 404 ───────────────────────────────────────────────────────
    console.warn(`[http] 404 Not found: ${method} ${path}`);
    return json({ error: "Not found" }, 404);
}


// ── POST /state — Engine pushes latest state ────────────────────
async function handlePostState(request: Request, env: Env): Promise<Response> {
    let state: SentinelState;

    // 1. Parse JSON body
    try {
        state = await request.json() as SentinelState;
    } catch (err) {
        console.error("[state] ❌ JSON parse failed:", err);
        return json({ error: "Invalid JSON body" }, 400);
    }

    // 2. Validate required fields
    if (!state.lastTickAt || !state.deadline || !state.stage) {
        console.warn("[state] Rejected: missing required fields", {
            lastTickAt: !!state.lastTickAt,
            deadline: !!state.deadline,
            stage: !!state.stage,
        });
        return json({ error: "Missing required fields: lastTickAt, deadline, stage" }, 400);
    }

    // 3. Write to KV
    const ok = await kvPut(env.SENTINEL_KV, "state", JSON.stringify(state));
    if (!ok) {
        return json({ error: "KV write failed — daily quota may be exceeded" }, 500);
    }

    console.log(`[state] ✅ Received — stage=${state.stage} deadline=${state.deadline} lastTick=${state.lastTickAt} stateChanged=${state.stateChanged} renewed=${state.renewedThisTick}`);
    return json({ ok: true, received: state.stage });
}


// ── POST /signal — Renew/release/urgent signal ──────────────────
async function handlePostSignal(request: Request, env: Env): Promise<Response> {
    let signal: Signal;

    try {
        signal = await request.json() as Signal;
    } catch (err) {
        console.error("[signal] ❌ JSON parse failed:", err);
        return json({ error: "Invalid JSON body" }, 400);
    }

    if (!signal.type || !signal.at) {
        console.warn("[signal] Rejected: missing required fields");
        return json({ error: "Missing required fields: type, at" }, 400);
    }

    const ok = await kvPut(env.SENTINEL_KV, "signal", JSON.stringify(signal));
    if (!ok) {
        return json({ error: "KV write failed — daily quota may be exceeded" }, 500);
    }

    console.log(`[signal] ✅ Received — type=${signal.type} at=${signal.at} nonce=${signal.nonce || "none"}`);
    return json({ ok: true, received: signal.type });
}


// ── POST /config — CLI wizard writes config ─────────────────────
async function handlePostConfig(request: Request, env: Env): Promise<Response> {
    let config: SentinelConfig;

    try {
        config = await request.json() as SentinelConfig;
    } catch (err) {
        console.error("[config] ❌ JSON parse failed:", err);
        return json({ error: "Invalid JSON body" }, 400);
    }

    if (!config.repo || !config.workflowFile) {
        console.warn("[config] Rejected: missing required fields");
        return json({ error: "Missing required fields: repo, workflowFile" }, 400);
    }

    const ok = await kvPut(env.SENTINEL_KV, "config", JSON.stringify(config));
    if (!ok) {
        return json({ error: "KV write failed — daily quota may be exceeded" }, 500);
    }

    console.log(`[config] ✅ Updated — repo=${config.repo} workflow=${config.workflowFile} cadence=${config.defaultCadenceMinutes}m thresholds=${config.thresholds.length} urgencyWindow=${config.urgencyWindowMinutes}m maxBackoff=${config.maxBackoffMinutes}m`);
    return json({ ok: true, repo: config.repo });
}


// ── POST /reset — Clear failures + optionally push state ────────
//    Body is optional.  If provided, treated as a state push too
//    (combined reset + sync in one call = 1 fewer round-trip).
async function handlePostReset(request: Request, env: Env): Promise<Response> {
    // Clear failures and lock
    const [f, l] = await Promise.all([
        kvDelete(env.SENTINEL_KV, "dispatch_failures"),
        kvDelete(env.SENTINEL_KV, "dispatch_lock"),
    ]);

    let stateResult: string | null = null;

    // Optionally accept a state payload in the same call
    try {
        const body = await request.text();
        if (body && body.trim().length > 0) {
            const state = JSON.parse(body) as SentinelState;
            if (state.lastTickAt && state.deadline && state.stage) {
                const ok = await kvPut(env.SENTINEL_KV, "state", JSON.stringify(state));
                stateResult = ok ? state.stage : "kv_failed";
                console.log(`[reset] State also updated → stage=${state.stage}`);
            }
        }
    } catch {
        // Body was empty or not valid JSON — that's fine, reset-only mode
    }

    console.log(`[reset] ✅ Dispatch failures and lock cleared (failures=${f}, lock=${l})`);
    return json({
        ok: true,
        message: "Dispatch failures and backoff cleared",
        stateUpdated: stateResult,
    });
}


// ── GET /status — Public observability endpoint ─────────────────
async function handleStatus(env: Env): Promise<Response> {
    const [stateRaw, signalRaw, configRaw, decisionRaw, dispatchLock, failCountRaw] = await Promise.all([
        env.SENTINEL_KV.get("state"),
        env.SENTINEL_KV.get("signal"),
        env.SENTINEL_KV.get("config"),
        env.SENTINEL_KV.get("last_decision"),
        env.SENTINEL_KV.get("dispatch_lock"),
        env.SENTINEL_KV.get("dispatch_failures"),
    ]);

    const state: SentinelState | null = stateRaw ? JSON.parse(stateRaw) : null;
    const signal: Signal | null = signalRaw ? JSON.parse(signalRaw) : null;
    const config: SentinelConfig | null = configRaw ? JSON.parse(configRaw) : null;
    const lastDecision: DecisionLog | null = decisionRaw ? JSON.parse(decisionRaw) : null;
    const dispatchFailures = failCountRaw ? parseInt(failCountRaw, 10) : 0;

    // Stale state detection: if lastTickAt is >2× cadence old, the engine is unhealthy
    const now = new Date();
    let staleMinutes: number | null = null;
    let engineHealthy = true;
    if (state && config) {
        staleMinutes = Math.round((now.getTime() - new Date(state.lastTickAt).getTime()) / 60_000);
        // If no tick in 2× cadence period, flag as stale
        if (staleMinutes > config.defaultCadenceMinutes * 2) {
            engineHealthy = false;
        }
    }

    console.log(`[status] configured=${!!config} hasState=${!!state} hasSignal=${!!signal} hasDecision=${!!lastDecision} hasLock=${!!dispatchLock} failures=${dispatchFailures} stale=${staleMinutes}m engineHealthy=${engineHealthy}`);

    return json({
        healthy: dispatchFailures === 0 && engineHealthy,
        configured: !!config,
        // State summary
        lastTickAt: state?.lastTickAt ?? null,
        stage: state?.stage ?? null,
        deadline: state?.deadline ?? null,
        stateChanged: state?.stateChanged ?? null,
        // Engine health
        engineHealthy,
        staleMinutes,
        // Decision info
        lastDecision: lastDecision ? {
            at: lastDecision.at,
            dispatch: lastDecision.dispatch,
            reason: lastDecision.reason,
        } : null,
        lastDispatchAt: dispatchLock ?? null,
        nextDueAt: config && state ? computeNextDueAt(state, config) : null,
        // Dispatch health
        dispatchFailures,
        dispatchHealthy: dispatchFailures === 0,
        // Signal info
        pendingSignal: signal ? { type: signal.type, at: signal.at } : null,
        // Config summary
        config: config ? {
            repo: config.repo,
            mirrorRepo: config.mirrorRepo ?? null,
            cadenceMinutes: config.defaultCadenceMinutes,
            thresholdCount: config.thresholds.length,
        } : null,
    });
}


// ─── Cron Handler ───────────────────────────────────────────────
async function handleScheduled(env: Env): Promise<void> {
    const now = new Date();
    console.log(`[cron] ──── Sentinel tick at ${now.toISOString()} ────`);

    // Read all KV keys in parallel
    const [stateRaw, signalRaw, configRaw, dispatchLock] = await Promise.all([
        env.SENTINEL_KV.get("state"),
        env.SENTINEL_KV.get("signal"),
        env.SENTINEL_KV.get("config"),
        env.SENTINEL_KV.get("dispatch_lock"),
    ]);

    const state: SentinelState | null = stateRaw ? JSON.parse(stateRaw) : null;
    const signal: Signal | null = signalRaw ? JSON.parse(signalRaw) : null;
    const config: SentinelConfig | null = configRaw ? JSON.parse(configRaw) : null;

    // Log KV state for observability
    console.log(`[cron] KV state: config=${!!config} state=${!!state} signal=${!!signal} lock=${!!dispatchLock}`);

    if (state) {
        const lastTickAge = Math.round((now.getTime() - new Date(state.lastTickAt).getTime()) / 60_000);
        const minutesToDeadline = Math.round((new Date(state.deadline).getTime() - now.getTime()) / 60_000);
        console.log(`[cron] Engine state: stage=${state.stage} lastTick=${lastTickAge}m ago deadline=${minutesToDeadline}m away renewed=${state.renewedThisTick}`);
    }
    if (signal) {
        console.log(`[cron] Pending signal: type=${signal.type} at=${signal.at}`);
    }
    if (dispatchLock) {
        const lockAge = Math.round((now.getTime() - new Date(dispatchLock).getTime()) / 1000);
        console.log(`[cron] Dispatch lock: ${dispatchLock} (${lockAge}s ago)`);
    }

    // No config = not set up yet, nothing to do
    if (!config) {
        console.warn("[cron] ⚠️ No config found in KV — run the setup wizard to configure the sentinel");
        return;
    }

    console.log(`[cron] Config: repo=${config.repo} cadence=${config.defaultCadenceMinutes}m urgency=${config.urgencyWindowMinutes}m backoff=${config.maxBackoffMinutes}m thresholds=${config.thresholds.length}`);

    // Read previous decision BEFORE computing new one — needed for:
    //   1. Bootstrap loop prevention (don't re-dispatch if already bootstrapped)
    //   2. KV write optimization (skip PUT if reason category unchanged)
    const prevDecisionRaw = await env.SENTINEL_KV.get("last_decision");
    const prevDecision = prevDecisionRaw ? JSON.parse(prevDecisionRaw) as DecisionLog : null;
    const prevReason = prevDecision?.reason ?? null;

    const decision = shouldDispatch(state, signal, config, now, dispatchLock, prevReason);

    // Build decision log for observability
    const decisionLog: DecisionLog = {
        at: now.toISOString(),
        dispatch: decision.dispatch,
        reason: decision.reason,
        state,
        signal,
        nextDueAt: computeNextDueAt(state, config),
    };

    // Only write to KV when the reason *category* changes (not dynamic values).
    // e.g. "backoff:2m/5m" and "backoff:3m/5m" are the same category "backoff".
    // This prevents 1,440 writes/day from backoff reason changes alone,
    // which exceeds the Cloudflare free-tier limit of 1,000 writes/day.
    const prevCategory = prevReason ? reasonCategory(prevReason) : null;
    const newCategory = reasonCategory(decision.reason);
    const categoryChanged = newCategory !== prevCategory;
    const dispatchChanged = decision.dispatch !== (prevDecision?.dispatch ?? false);

    if (decision.dispatch || categoryChanged || dispatchChanged) {
        await kvPut(env.SENTINEL_KV, "last_decision", JSON.stringify(decisionLog));
    }

    if (decision.dispatch) {
        console.log(`[cron] ✅ DISPATCH — reason: ${decision.reason}`);
    } else {
        console.log(`[cron] ⏭️ SKIP — reason: ${decision.reason}`);
    }

    if (!decision.dispatch) {
        const nextDue = decisionLog.nextDueAt;
        if (nextDue) {
            const nextDueMin = Math.round((new Date(nextDue).getTime() - now.getTime()) / 60_000);
            console.log(`[cron] Next due in ~${nextDueMin}m (${nextDue})`);
        }
        return;
    }

    // ── Dispatch ──────────────────────────────────────────────────

    // Acquire lock (TTL = backoff window so the key survives until next dispatch is allowed)
    const lockTtlSeconds = Math.max(config.maxBackoffMinutes * 60, 120);
    await kvPut(env.SENTINEL_KV, "dispatch_lock", now.toISOString(), { expirationTtl: lockTtlSeconds });
    console.log(`[cron] Lock acquired (TTL=${lockTtlSeconds}s), dispatching to ${config.repo}/${config.workflowFile}...`);

    let success = await dispatchWorkflow(config, env.GITHUB_TOKEN, decision.reason);

    // ── Mirror failover: if primary dispatch fails and mirrorRepo is configured,
    //    try dispatching to the mirror repo with its own token.
    if (!success && config.mirrorRepo) {
        const mirrorToken = env.GITHUB_MIRROR_TOKEN;
        if (!mirrorToken) {
            console.warn(`[cron] Mirror configured (${config.mirrorRepo}) but GITHUB_MIRROR_TOKEN not set — skipping failover`);
        } else {
            console.warn(`[cron] Primary dispatch failed — trying mirror: ${config.mirrorRepo}`);
            const mirrorConfig = { ...config, repo: config.mirrorRepo };
            success = await dispatchWorkflow(mirrorConfig, mirrorToken, `mirror:${decision.reason}`);
            if (success) {
                console.log(`[cron] ✅ Mirror dispatch succeeded — workflow triggered on ${config.mirrorRepo}`);
            }
        }
    }

    if (success) {
        console.log(`[cron] ✅ Dispatch succeeded — workflow triggered on ${config.repo}`);
        // Clear failure counter on success (use kvDelete for safety)
        await kvDelete(env.SENTINEL_KV, "dispatch_failures");
        // Clear the consumed signal
        if (signal) {
            await kvDelete(env.SENTINEL_KV, "signal");
            console.log(`[cron] Signal consumed and cleared: type=${signal.type}`);
        }
    } else {
        // On failure: keep the lock (don't delete!) so backoff applies.
        // Also track consecutive failures for exponential backoff.
        const failCountRaw = await env.SENTINEL_KV.get("dispatch_failures");
        const failCount = failCountRaw ? parseInt(failCountRaw, 10) + 1 : 1;
        // Exponential backoff: 5m, 10m, 20m, 40m, capped at 60m
        const extendedBackoffMin = Math.min(config.maxBackoffMinutes * Math.pow(2, failCount - 1), 60);
        const extendedTtl = Math.max(extendedBackoffMin * 60, lockTtlSeconds);
        await kvPut(env.SENTINEL_KV, "dispatch_lock", now.toISOString(), { expirationTtl: extendedTtl });
        await kvPut(env.SENTINEL_KV, "dispatch_failures", String(failCount));
        console.error(`[cron] ❌ Dispatch FAILED (attempt #${failCount}) — backoff extended to ${extendedBackoffMin}m`);
    }
}


// ─── Export ─────────────────────────────────────────────────────
export default {
    async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
        return handleFetch(request, env);
    },

    async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext): Promise<void> {
        ctx.waitUntil(handleScheduled(env));
    },
};
