/**
 * GitHub Dispatch — Trigger a workflow_dispatch event via the GitHub API.
 *
 * This is how the sentinel "pokes" the real tick pipeline.
 */

import type { SentinelConfig } from "./types";

/**
 * Dispatch a GitHub Actions workflow via the REST API.
 *
 * @param config      - Sentinel config (contains repo + workflow file)
 * @param githubToken - Fine-grained PAT with actions:write scope
 * @param reason      - Why we're dispatching (logged as workflow input)
 * @returns           - True if dispatch succeeded, false otherwise
 */
export async function dispatchWorkflow(
    config: SentinelConfig,
    githubToken: string,
    reason: string,
): Promise<boolean> {
    const repo = config.repo;
    if (!repo) {
        console.error("[dispatch] No repo configured");
        return false;
    }

    const url = `https://api.github.com/repos/${repo}/actions/workflows/${config.workflowFile}/dispatches`;

    try {
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${githubToken}`,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "continuity-sentinel/1.0",
            },
            body: JSON.stringify({
                ref: "main",
                inputs: {
                    reason: `sentinel:${reason}`,
                },
            }),
        });

        if (response.status === 204) {
            console.log(`[dispatch] ✅ Dispatched to ${repo} — reason: ${reason}`);
            return true;
        }

        const body = await response.text();
        console.error(`[dispatch] ❌ GitHub API returned ${response.status}: ${body}`);
        return false;

    } catch (err) {
        console.error(`[dispatch] ❌ Failed to dispatch:`, err);
        return false;
    }
}
