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
        console.error("[dispatch] ❌ No repo configured");
        return false;
    }

    if (!githubToken) {
        console.error("[dispatch] ❌ No GITHUB_TOKEN secret set — cannot dispatch");
        return false;
    }

    const url = `https://api.github.com/repos/${repo}/actions/workflows/${config.workflowFile}/dispatches`;
    console.log(`[dispatch] POST ${url} — reason: ${reason}`);

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
            console.log(`[dispatch] ✅ Success — dispatched ${config.workflowFile} on ${repo} (reason: ${reason})`);
            return true;
        }

        const body = await response.text();
        console.error(`[dispatch] ❌ GitHub API returned ${response.status}: ${body.substring(0, 500)}`);

        // Log common error hints
        if (response.status === 401) {
            console.error("[dispatch] 💡 GITHUB_TOKEN may be expired or invalid");
        } else if (response.status === 404) {
            console.error(`[dispatch] 💡 Repo '${repo}' or workflow '${config.workflowFile}' not found — check config`);
        } else if (response.status === 422) {
            console.error("[dispatch] 💡 Workflow may not have workflow_dispatch trigger or 'reason' input");
        }

        return false;

    } catch (err) {
        console.error(`[dispatch] ❌ Network error:`, err);
        return false;
    }
}
