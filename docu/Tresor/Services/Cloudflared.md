# ☁️ Cloudflared — Public Access Layer

## Overview

Cloudflared acts as Tresor’s **public ingress** — a single secure tunnel from Cloudflare’s edge to my **Traefik** reverse proxy on the `public_net`.  
No router ports are opened; all HTTPS traffic is encrypted end-to-end via the Cloudflare Tunnel token.

| Component | Role | Host | Network |
| --- | --- | --- | --- |
| **Cloudflared** | Establishes CF Tunnel to `example.com` | `tresor` | `public_net` |
| **Traefik** | Reverse proxy for public services | `tresor` | `public_net` |
| **Cloudflare DNS** | Points `*.example.com` → Tunnel ID | Managed in Cloudflare Dashboard |     |

* * *

## Runtime Profile

| Setting | Value |
| --- | --- |
| **Mode** | Token-based (persistent CF-managed tunnel) |
| **Image** | `cloudflare/cloudflared:latest` |
| **Network** | `public_net` (shared with Traefik) |
| **Metrics** | Disabled in prod (can enable on port 8086 for debugging) |
| **Logs** | `/var/lib/docker/containers/cloudflared*/cloudflared-json.log` |
| **TZ** | `UTC` |
| **Managed by** | `roles/cloudflared` |

* * *

## Role Behavior (`roles/cloudflared`)

- **Token-only mode — no config files on disk.** Routing is managed entirely in the Cloudflare Dashboard (no `config.yml`, no `credentials-file`).

- Builds effective config via `set_fact` (merges role defaults with any inventory overrides).

- Token resolution order (first defined wins):
  1. `cloudflared.token` in inventory group_vars
  2. `vault_cloudflared_token` (Ansible Vault)
  3. env var `CF_TUNNEL_TOKEN`
  4. extra-var `cf_token`

- Runs container as: `tunnel --no-autoupdate run --token <token>`

- Supports both QA and PROD modes:
    - QA → disabled via `cloudflared.enabled: false` → `meta: end_host`
    - PROD → token-based tunnel with `vault_cloudflared_token`

- Handles graceful skips: status play won’t fail if disabled.
    

* * *

## Security Model

- **Zero open ports**: all ingress handled by CF edge.
    
- **Outbound-only**: Cloudflared dials out to Cloudflare; no inbound allowed.
    
- **Token authentication** ensures the tunnel can’t be hijacked or recreated externally.
    
- **No sensitive data** (tunnel UUID/token) stored in repo — pulled from vault.
    
- **Traefik dashboard** is off in prod; all apps use subdomains via CF DNS:
    
    ```
    status.example.com   → Uptime Kuma
    mc.example.com       → MC frontend
    cv.example.com       → Personal site
    ```
    
- Fail2Ban + UFW still run on host for defense in depth, though inbound isn’t used.
    

* * *

## Gotchas

| Issue | Cause | Fix |
| --- | --- | --- |
| “Token not authorized” | Vault token expired or revoked | Refresh `vault_cloudflared_token` |
| Tunnel reconnects every few minutes | Mis-set timezone or clock drift | Ensure NTP sync (`setup-base` handles it) |
| `/metrics` unreachable | `enable_metrics: false` in prod | Set true in vars for debug |
| `public_net` missing | Skipped network role | Run `setup-networks.yml` once |

> **Note:** When the tunnel reconnects, you might briefly see `ERR_SSL_PROTOCOL_ERROR` on the browser — normal during restarts.

* * *

## Integration Notes

- **Traefik** binds internally to `public_net`; CF points to it by container name.
    
- **DNS & SSL** are managed entirely in Cloudflare — no certs on host.
    
- All public-facing services (MC Frontend, CV site, Uptime Kuma, etc.) flow through:
    
    ```
    Browser → CF Edge → Cloudflared (Docker) → Traefik → Container
    ```
    
- Each service is still isolated; Cloudflared doesn’t expose any Docker socket or host path beyond its config.
    

* * *

## Monitoring

- Health checked via Ansible’s `cloudflared/status.yml`:
    
    - Confirms container running & healthy.
        
    - Optionally probes `/metrics` endpoint if enabled.
        
- cAdvisor covers runtime stats.
    
- Log pattern for uptime confirmation:
    
    ```
    INF Connection established connIndex=0 location=SOF
    ```
    
- Grafana can scrape metrics if `enable_metrics: true`.
    

* * *

## Maintenance

| Task | Command |
| --- | --- |
| Restart tunnel | `ansible-playbook playbooks/cloudflared/restart.yml` |
| Stop tunnel | `ansible-playbook playbooks/cloudflared/stop.yml` |
| Check health | `ansible-playbook playbooks/cloudflared/status.yml` |
| View logs | `ssh tresor 'docker logs -n 50 cloudflared'` |

* * *

&nbsp;