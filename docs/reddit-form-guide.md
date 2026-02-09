# Reddit API Request — Form Fill-In Guide

Use this document to copy/paste into each field of the Reddit API Access Request form.

---

## Field: "Your email address"
```
jfm.devops.expert@gmail.com
```

## Field: "Which role best describes your reason for requesting API access?"
```
I'm a developer
```
✅ Correct choice — this is a bot/app that uses the API programmatically.

## Field: "What is your inquiry?"
```
I'm a developer and want to build a Reddit App that does not work in the Devvit ecosystem.
```
✅ Correct choice — your app runs externally (GitHub Actions / self-hosted) and only uses
the API to post. It cannot be built with Devvit, which is for in-platform apps.

---

## Field: "Reddit account name"
```
u/SpecialZestyclose255
```

---

## Field: "What benefit/purpose will the bot/app have for Redditors?"

```
Continuity Orchestrator is a personal safety and accountability tool. It acts as a "dead man's switch" — if the operator fails to check in within a configurable deadline, the system posts automated status updates to their own subreddit to alert anyone who follows them.

Use cases include:
- Solo travelers posting a safety alert if they fail to check in after a remote trip
- Independent journalists/researchers making information available if they become unreachable
- Anyone who wants a public, timestamped continuity signal

The benefit to Redditors: if someone subscribes to the operator's subreddit, they receive a transparent, timestamped notification that the operator may need help — rather than silence. It turns Reddit into a verifiable public record of continuity status.

The bot only posts to the operator's own subreddit. It does not interact with any other users, posts, or communities.
```

---

## Field: "Provide a detailed description of what the Bot/App will be doing on the Reddit platform."

```
The app is a "script" type OAuth2 application for single-user, personal use.

WHAT IT DOES:
1. Authenticates via OAuth2 password grant (script app flow) as the operator
2. Posts text-only self-posts to the operator's OWN subreddit (e.g., r/ContinuityStatus)
3. Posts are triggered ONLY when the operator misses a check-in deadline

POSTS LOOK LIKE:
- Title: "[Automated] ⚠️ Continuity Check-in Overdue — Escalation Level 2"
- Body contains the current status, a link to the public status page, and a clear footer: "🤖 This post was generated automatically by Continuity Orchestrator"

API ENDPOINTS USED (only 3):
- POST /api/v1/access_token — OAuth2 token refresh
- POST /api/submit — Submit a self-post
- GET /api/v1/me — Credential verification (setup/testing only)

VOLUME:
- 0–3 posts per day during active escalation
- 0–10 posts per month typical
- < 1 API call per minute (well below 100 QPM limit)
- Many months will see ZERO posts

WHAT IT DOES NOT DO:
- Never reads, scrapes, or collects any Reddit content
- Never interacts with other users' posts or comments
- Never votes, follows, or engages with other accounts
- Never accesses any subreddit other than the operator's own
- No AI/ML, no data harvesting, no commercial use

All posts are clearly labeled as automated with [Automated] prefix and bot footer.
User-Agent: python:continuity-orchestrator:v1.0 (by /u/SpecialZestyclose255)

The project is open-source: https://github.com/cyberpunk042/continuity-orchestrator
Live public site: https://cyberpunk042.github.io/continuity-orchestrator/
```

---

## Field: "What is missing from Devvit that prevents building on that platform?"

```
This application cannot be built with Devvit because it is an external, self-hosted system that runs outside of Reddit — either as a GitHub Actions workflow or a local CLI tool.

Specifically:
1. The app needs to run on a schedule OUTSIDE Reddit (GitHub Actions cron job or local timer), evaluate state from a local JSON file, and conditionally post TO Reddit. Devvit apps run inside Reddit's infrastructure and cannot access external state.

2. The "dead man's switch" pattern requires the app to operate independently of Reddit — it must be able to check-in status, send emails, send SMS, post to X/Twitter, AND post to Reddit as part of a multi-channel escalation. Reddit is just one of several notification outputs.

3. The app uses the simple "script" OAuth2 flow for single-user personal use. It's a straightforward POST-only integration — it submits self-posts and nothing else. There's no interactive component, no custom UI, no widget, no custom post type — none of the things Devvit is designed for.

In short: it's an external automation tool that happens to use Reddit as one of several notification channels. It's architecturally incompatible with Devvit's in-platform model.
```

---

## Field: "Provide a link to source code or platform that will access the API."

```
https://github.com/cyberpunk042/continuity-orchestrator

The Reddit adapter code is at: src/adapters/reddit.py
The project's public status site: https://cyberpunk042.github.io/continuity-orchestrator/
Privacy Policy: https://cyberpunk042.github.io/continuity-orchestrator/privacy.html
Terms of Use: https://cyberpunk042.github.io/continuity-orchestrator/terms.html
```

---

## Field: "What subreddits do you intend to use the bot/app in?"

```
Only in my own personal subreddit(s), such as r/ContinuityStatus or my user profile.
The app is configured to post exclusively to subreddit(s) owned by the operator.
It does not and cannot post to any other community.
```

---

## Field: "If applicable, what username will you be operating this bot/app under?"

```
u/SpecialZestyclose255
```

---

## Field: "Attachments"

Upload these files from the docs/ folder:
- docs/reddit-flow-diagram.png — Technical flow showing the Reddit API integration
- docs/reddit-post-example.png — Mock-up of what an automated Reddit post looks like
- docs/reddit-api-request.md — Full detailed request document (optional, for completeness)
