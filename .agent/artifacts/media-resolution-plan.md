# Media Resolution in the Send Path — Implementation Plan

## The Two Problems

**Problem A:** `media://` URIs need to be resolved to public URLs before
content reaches adapters.

**Problem B:** The Resend adapter's `_markdown_to_html()` needs to handle
`![](url)` BEFORE the link regex — currently it has no media handling.

## Public URL Resolution (`get_site_base_url()`)

Priority chain:
1. `ARCHIVE_URL` (explicit override — always wins)
2. Cloudflare tunnel detection: decode `CLOUDFLARE_TUNNEL_TOKEN` (base64
   JSON `{a: account_id, t: tunnel_id, s: secret}`) → query CF API
   for tunnel hostname from ingress rules
3. `GITHUB_REPOSITORY` → `https://{owner}.github.io/{repo}`
4. None → strip media to text labels, log warning

## Implementation — DONE

### ✅ Step 1: `src/templates/media.py` (NEW)
- `get_site_base_url()` — resolution chain above
- `_detect_cloudflare_tunnel_url()` — decode token, query CF API
- `resolve_media_uris(text, stage)` — resolve media:// to public URLs
- `media_md_to_html(text)` — markdown media → HTML (extracted from routes_messages)
- `strip_media_to_labels(text)` — media → text labels (extracted from routes_messages)

### ✅ Step 2: `src/engine/tick.py`
- After `resolve_and_render()`, call `resolve_media_uris(template_content, stage=current_stage)`

### ✅ Step 3: `src/adapters/email_resend.py`
- Import + call `media_md_to_html()` before link regex in `_markdown_to_html()`

### ✅ Step 4: `src/admin/routes_messages.py`
- Replaced local `_media_md_to_html` and `_strip_media_for_plaintext` with
  imports from `src/templates/media.py`

### Step 5: Docker env vars
- Add `ARCHIVE_URL` and `CLOUDFLARE_TUNNEL_TOKEN` to orchestrator containers
  in docker-compose.yml (both standalone and git-sync variants)
