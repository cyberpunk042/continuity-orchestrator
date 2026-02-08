# Task B: Cloudflared Tunnel Sidecar

## Problem

The Docker deployment (Mode 2: git-sync) serves the static site via nginx on
`localhost:8080`. To expose it publicly without port-forwarding, firewall holes,
or a static IP, users need a Cloudflare Tunnel — but there's no built-in
support for it.

## Analysis: What connects

### 1. Docker networking (docker-compose.yml)

**nginx** is the only service with a `ports:` binding (`8080:80`). All services
share `continuity-net`. cloudflared needs to reach nginx on this internal
network via `http://nginx:80`. It does NOT need a port binding of its own.

**Profile strategy:** The existing profiles are:
- (none) — standalone mode
- `git-sync` — git-synced mode
- `observer` — read-only mode
- `tools` — one-shot utilities

cloudflared should be its own profile (`tunnel`) so users opt in independently:
```
docker compose --profile git-sync --profile tunnel up -d
```

### 2. Environment / secrets tier (_secrets.html)

`CLOUDFLARE_TUNNEL_TOKEN` must go in **LOCAL_ONLY** tier — it's a runtime
secret for the Docker host, never pushed to GitHub.

It must appear in:
- `LOCAL_ONLY` array (line 44)
- `SECRET_DEFINITIONS` in system_status.py (guidance text)
- A category in the secrets panel — new group: **"Docker / Tunnel"**
  - Include: `DEPLOY_MODE`, `CLOUDFLARE_TUNNEL_TOKEN`,
    `DOCKER_GIT_SYNC_ALPHA`, `DOCKER_GIT_SYNC_TICK_INTERVAL`,
    `DOCKER_GIT_SYNC_SYNC_INTERVAL`
  - This clusters all Docker-specific config together instead of scattering
    it across "Operational" or leaving it ungrouped
- `nonSensitive` list — **NO**. The token is a secret.
- `booleanSecrets` list — no.

### 3. Wizard (_wizard.html)

The Deploy step already shows Docker options (alpha mode, tick/sync intervals).
When Docker mode is selected, add a field for the tunnel token:
- Below the git-sync settings panel
- Optional — not required to proceed
- Tooltip: "Get from Cloudflare Zero Trust dashboard → Networks → Tunnels → Create"

The collect function already gathers Docker-specific values when `mode === 'docker'`.
We add `CLOUDFLARE_TUNNEL_TOKEN` there.

### 4. The header/mode docs (top of docker-compose.yml)

The deployment mode docs (lines 1-20) should mention the tunnel profile as a
composable add-on.

### 5. No admin panel status indicator (yet)

We could show "tunnel: connected" in the debugging tab, but cloudflared doesn't
expose a local API by default, so there's nothing to poll. Skip for now.

## Implementation Plan

### File 1: docker-compose.yml

Add cloudflared service:

```yaml
  # ==========================================================================
  # CLOUDFLARE TUNNEL — Expose site via Cloudflare (optional)
  # ==========================================================================
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: continuity-tunnel
    restart: unless-stopped
    profiles:
      - tunnel
    depends_on:
      - nginx
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN:-}
    networks:
      - continuity-net
```

Update the header docs to mention `--profile tunnel`.

### File 2: system_status.py

Add to SECRET_DEFINITIONS:
```python
"CLOUDFLARE_TUNNEL_TOKEN": {
    "required_for": ["tunnel"],
    "guidance": "Token from Cloudflare Zero Trust → Networks → Tunnels. Required for Docker tunnel profile."
},
```

### File 3: _secrets.html

1. Add `CLOUDFLARE_TUNNEL_TOKEN` to `LOCAL_ONLY` array
2. Add a **"Docker / Tunnel"** category that groups all Docker-specific env vars:
   `['DEPLOY_MODE', 'CLOUDFLARE_TUNNEL_TOKEN', 'DOCKER_GIT_SYNC_ALPHA',
     'DOCKER_GIT_SYNC_TICK_INTERVAL', 'DOCKER_GIT_SYNC_SYNC_INTERVAL']`
3. Move `DEPLOY_MODE` out of wherever it currently sits into this new group
4. Map the category to wizard step 'deployment' for the shortcut link

### File 4: _wizard.html

Add tunnel token field in the Docker settings panel:
```html
<div class="form-group" style="margin-top: 1rem;">
    <label class="form-label" style="font-size: 0.85rem;">
        Cloudflare Tunnel Token <span style="color: var(--text-dim);">(optional)</span>
    </label>
    <input type="password" class="form-input" id="wiz-tunnel-token"
        value="${wizardData.CLOUDFLARE_TUNNEL_TOKEN || ''}"
        placeholder="eyJhIjoi..."
        onchange="wizardData.CLOUDFLARE_TUNNEL_TOKEN = this.value">
    <span style="color: var(--text-dim); font-size: 0.75rem;">
        Get from Cloudflare Zero Trust → Networks → Tunnels → Create a tunnel
    </span>
</div>
```

Update collect to include it:
```javascript
data.CLOUDFLARE_TUNNEL_TOKEN = document.getElementById('wiz-tunnel-token')?.value || '';
```

### File 5: No new tests needed

cloudflared is a stock Docker image with zero custom logic — it's pure config.
The service declaration is validated by `docker compose config` (which we can
run as a CI check, but that's a separate concern).

## Touch points summary

| File | Change |
|------|--------|
| `docker-compose.yml` | + cloudflared service, update header docs |
| `system_status.py` | + CLOUDFLARE_TUNNEL_TOKEN guidance |
| `_secrets.html` | + LOCAL_ONLY, + "Docker / Tunnel" category, wizard shortcut |
| `_wizard.html` | + tunnel token input in Docker settings panel |

## Risk

Low — additive only, behind a profile gate, no existing behaviour changes.
