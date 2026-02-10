/**
 * Continuity Sentinel — Cloudflare Worker Entry Point
 *
 * Two handlers:
 *   fetch()     — HTTP API for receiving state/signals + serving status
 *   scheduled() — Cron trigger (every minute) that decides whether to dispatch
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
        return handlePostReset(env);
    }

    // ── 404 ───────────────────────────────────────────────────────
    console.warn(`[http] 404 Not found: ${method} ${path}`);
    return json({ error: "Not found" }, 404);
}


// ── POST /state — Engine pushes latest state ────────────────────
async function handlePostState(request: Request, env: Env): Promise<Response> {
    try {
        const state = await request.json() as SentinelState;

        // Basic validation
        if (!state.lastTickAt || !state.deadline || !state.stage) {
            console.warn("[state] Rejected: missing required fields");
            return json({ error: "Missing required fields: lastTickAt, deadline, stage" }, 400);
        }

        await env.SENTINEL_KV.put("state", JSON.stringify(state));

        console.log(`[state] ✅ Received — stage=${state.stage} deadline=${state.deadline} lastTick=${state.lastTickAt} stateChanged=${state.stateChanged} renewed=${state.renewedThisTick}`);
        return json({ ok: true, received: state.stage });

    } catch (err) {
        console.error("[state] ❌ Invalid JSON body:", err);
        return json({ error: "Invalid JSON body" }, 400);
    }
}


// ── POST /signal — Renew/release/urgent signal ──────────────────
async function handlePostSignal(request: Request, env: Env): Promise<Response> {
    try {
        const signal = await request.json() as Signal;

        if (!signal.type || !signal.at) {
            console.warn("[signal] Rejected: missing required fields");
            return json({ error: "Missing required fields: type, at" }, 400);
        }

        await env.SENTINEL_KV.put("signal", JSON.stringify(signal));

        console.log(`[signal] ✅ Received — type=${signal.type} at=${signal.at} nonce=${signal.nonce || "none"}`);
        return json({ ok: true, received: signal.type });

    } catch (err) {
        console.error("[signal] ❌ Invalid JSON body:", err);
        return json({ error: "Invalid JSON body" }, 400);
    }
}


// ── POST /config — CLI wizard writes config ─────────────────────
async function handlePostConfig(request: Request, env: Env): Promise<Response> {
    try {
        const config = await request.json() as SentinelConfig;

        if (!config.repo || !config.workflowFile) {
            console.warn("[config] Rejected: missing required fields");
            return json({ error: "Missing required fields: repo, workflowFile" }, 400);
        }

        await env.SENTINEL_KV.put("config", JSON.stringify(config));

        console.log(`[config] ✅ Updated — repo=${config.repo} workflow=${config.workflowFile} cadence=${config.defaultCadenceMinutes}m thresholds=${config.thresholds.length} urgencyWindow=${config.urgencyWindowMinutes}m maxBackoff=${config.maxBackoffMinutes}m`);
        return json({ ok: true, repo: config.repo });

    } catch (err) {
        console.error("[config] ❌ Invalid JSON body:", err);
        return json({ error: "Invalid JSON body" }, 400);
    }
}


// ── POST /reset — Clear dispatch failures and backoff lock ──────
async function handlePostReset(env: Env): Promise<Response> {
    await Promise.all([
        env.SENTINEL_KV.delete("dispatch_failures"),
        env.SENTINEL_KV.delete("dispatch_lock"),
    ]);

    console.log("[reset] ✅ Dispatch failures and lock cleared");
    return json({ ok: true, message: "Dispatch failures and backoff cleared" });
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

    console.log(`[status] configured=${!!config} hasState=${!!state} hasSignal=${!!signal} hasDecision=${!!lastDecision} hasLock=${!!dispatchLock} failures=${dispatchFailures}`);

    return json({
        healthy: dispatchFailures === 0,
        configured: !!config,
        // State summary
        lastTickAt: state?.lastTickAt ?? null,
        stage: state?.stage ?? null,
        deadline: state?.deadline ?? null,
        stateChanged: state?.stateChanged ?? null,
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
    //   2. KV write optimization (skip PUT if reason unchanged)
    const prevDecisionRaw = await env.SENTINEL_KV.get("last_decision");
    const prevReason = prevDecisionRaw ? (JSON.parse(prevDecisionRaw) as DecisionLog).reason : null;

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
    if (decision.dispatch || decision.reason !== prevReason) {
        await env.SENTINEL_KV.put("last_decision", JSON.stringify(decisionLog));
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
    await env.SENTINEL_KV.put("dispatch_lock", now.toISOString(), { expirationTtl: lockTtlSeconds });
    console.log(`[cron] Lock acquired (TTL=${lockTtlSeconds}s), dispatching to ${config.repo}/${config.workflowFile}...`);

    const success = await dispatchWorkflow(config, env.GITHUB_TOKEN, decision.reason);

    if (success) {
        console.log(`[cron] ✅ Dispatch succeeded — workflow triggered on ${config.repo}`);
        // Clear failure counter on success
        await env.SENTINEL_KV.delete("dispatch_failures");
        // Clear the consumed signal
        if (signal) {
            await env.SENTINEL_KV.delete("signal");
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
        await env.SENTINEL_KV.put("dispatch_lock", now.toISOString(), { expirationTtl: extendedTtl });
        await env.SENTINEL_KV.put("dispatch_failures", String(failCount));
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
