# 🎵 Nginx-Music — Public Jellyfin Streaming via VPS Reverse Proxy

## Overview

Nginx-Music is Tresor's **public media streaming layer** — an nginx reverse proxy on the VPS that forwards HTTPS traffic through the WireGuard tunnel to a dedicated Jellyfin instance (`jellyfin-music`) on the home node.

This exists because **Cloudflare Tunnel's TOS prohibits video/audio streaming traffic**. Rather than risking a CF account ban, all media streaming bypasses Cloudflare entirely and goes through the VPS directly with Let's Encrypt TLS.

| Component | Host | Role | Network |
| --- | --- | --- | --- |
| **Nginx** | `tresor-vps` | TLS termination + reverse proxy | public (ports 80, 443) |
| **WireGuard** | `tresor-vps` ↔ `tresor` | Encrypted tunnel | `10.66.66.0/24` |
| **Jellyfin-Music** | `tresor` | Dedicated streaming instance | `bridge` + `internal_net`, bound to `10.66.66.2:18096` |

```
Browser / App
    ↓ HTTPS (443)
music.example.com (VPS public IP)
    ↓ nginx reverse proxy
    ↓ TLS terminated (Let's Encrypt)
WireGuard tunnel (10.66.66.1 → 10.66.66.2)
    ↓ HTTP (18096)
jellyfin-music container (Tresor)
```

> **Key distinction:** This is a completely separate Jellyfin instance from the LAN-only `jellyfin` container. The LAN instance serves the full media library on `192.168.1.100:8096`. The public instance (`jellyfin-music`) is locked to `10.66.66.2:18096` and only accessible through the VPS.

* * *

## Why Not Cloudflare Tunnel?

Cloudflare's [Self-Serve Subscription Agreement §2.8](https://www.cloudflare.com/terms/) prohibits using their network to serve disproportionate amounts of non-HTML content — specifically video and audio streaming. While enforcement varies, violating TOS risks account termination, which would take down all other services routed through the tunnel (Uptime Kuma, landing site, etc.).

The VPS reverse proxy solution:

- **No CF dependency** for streaming traffic
- **Direct TLS** via Let's Encrypt (no CF edge involved)
- **Same WireGuard tunnel** already in use for Minecraft
- **Minimal cost** — VPS already paid for

* * *

## Runtime Profile

| Setting | Value |
| --- | --- |
| **Domain** | `music.example.com` |
| **TLS** | Let's Encrypt via Certbot (nginx plugin) |
| **Upstream** | `10.66.66.2:18096` (over WireGuard) |
| **Nginx config** | `/etc/nginx/sites-available/music.conf` |
| **Cert path** | `/etc/letsencrypt/live/music.example.com/` |
| **Managed by** | `roles/nginx-music` |
| **Rate limiting** | 10 req/s general, 5 req/s strict (login/websockets) |
| **Connection limit** | 20 concurrent per IP |
| **Max upload** | 50M |
| **HSTS** | Enabled |

* * *

## Role Behavior (`roles/nginx-music`)

### Deployment flow:

1.  Installs `nginx`, `certbot`, `python3-certbot-nginx`
2.  Opens UFW ports 80/443
3.  Renders HTTP-only bootstrap config (for ACME challenge)
4.  Issues Let's Encrypt cert via `certbot --nginx`
5.  Renders full TLS config with security hardening
6.  Reloads nginx

### Pre-flight:

- Probes `10.66.66.2:18096` over WireGuard before deploying
- Warns (but continues) if backend unreachable — allows cert issuance even if Tresor is temporarily down

### Config templates:

- `music.http.nginx.j2` — minimal HTTP config for initial cert issuance
- `music.tls.nginx.j2` — full production config with TLS, rate limiting, security headers, and API blocking

* * *

## Security Model

### Network layer

- Nginx listens on VPS public IP (ports 80/443 only)
- All traffic to Jellyfin goes through encrypted WireGuard tunnel
- `jellyfin-music` is bound exclusively to `10.66.66.2:18096` — unreachable from LAN or public internet
- UFW on VPS allows only: 22/tcp, 51820/udp, 25565/tcp, 80/tcp, 443/tcp

### Application layer (nginx hardening)

**Rate limiting:**

- General requests: 10 req/s with burst of 20
- Strict endpoints (login, websockets): 5 req/s with burst of 5

**Connection limits:**

- Max 20 concurrent connections per IP

**Security headers:**

- `X-Frame-Options: SAMEORIGIN`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy` — disables geolocation, microphone, camera, payment, USB
- Content Security Policy tuned for Jellyfin UI

**Blocked API endpoints:**

The following paths are blocked at the nginx level to prevent information leakage:

- `/System/*`, `/Users/*`, `/Branding/*`, `/health`, `/Sessions/*`, `/Devices/*` — system info and user enumeration
- `/swagger`, `/api-docs`, `/manage`, `/admin` — admin/debug interfaces
- `/Items/*/File`, `/Audio/*/universal`, `/Videos/*/stream` — direct file download bypass

**Allowed HTTP methods:** GET, POST, HEAD, OPTIONS only

**Logging:**

- Blocked requests → `/var/log/nginx/jellyfin_blocked.log`
- Denied requests → `/var/log/nginx/jellyfin_denied.log`

* * *

## Container Profile (`jellyfin-music`)

| Setting | Value |
| --- | --- |
| **Container name** | `jellyfin-music` |
| **Image** | `jellyfin/jellyfin:latest` |
| **Bind address** | `10.66.66.2:18096` (WG interface only) |
| **Networks** | `bridge`, `internal_net` |
| **Media** | Same library as LAN Jellyfin (mounted RO) |
| **Config** | Separate config dir from LAN instance |

> This is a dedicated instance with its own config, users, and playback state. It shares the media library via read-only mounts but is otherwise fully isolated from the LAN Jellyfin.

* * *

## Packet Flow (detailed)

```
Client (phone/browser)
    ↓ DNS: music.example.com → 1.2.3.4 (your-vps-provider VPS)
    ↓ TCP 443 (HTTPS)
VPS nginx (TLS termination)
    ↓ rate limit + security headers + API blocking
    ↓ proxy_pass http://10.66.66.2:18096
WireGuard tunnel (UDP 51820)
    ↓ 10.66.66.1 → 10.66.66.2
Tresor — jellyfin-music container
    ↓ bound to 10.66.66.2:18096 only
    ↓ serves media from /mnt/hdd/data/media (RO)
```

* * *

## Relationship to Other Services

| Service | Path | Notes |
| --- | --- | --- |
| **jellyfin** (LAN) | `192.168.1.100:8096` | Full media server, LAN-only, VAAPI HW accel |
| **jellyfin-music** (public) | `10.66.66.2:18096` via VPS | Public streaming, WG-only, nginx TLS frontend |
| **Cloudflare Tunnel** | `*.example.com` (non-streaming) | Web apps only — no media traffic |
| **Velocity** (MC) | `1.2.3.4:25565` | Shares VPS but completely separate |

> **No streaming traffic touches Cloudflare.** Web services go through CF Tunnel → Traefik. Media streaming goes through VPS nginx → WireGuard → jellyfin-music. These paths are fully independent.

* * *

## Troubleshooting

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| 502 Bad Gateway | WireGuard tunnel down or jellyfin-music stopped | `sudo wg show` on both nodes; `docker ps` on tresor |
| Cert renewal fails | Port 80 blocked or nginx misconfigured | `sudo certbot renew --dry-run`; check UFW |
| Slow playback / buffering | WG latency or bandwidth cap | Check `wg show` transfer stats; test with `iperf3` |
| 403 on API endpoints | nginx blocks sensitive paths by design | Expected behavior — check `jellyfin_blocked.log` |
| Rate limited (429) | Too many requests from single IP | Adjust `nginx_music_rate_limit_*` vars |
| "Connection refused" in nginx logs | jellyfin-music not bound to WG IP | Verify `docker inspect jellyfin-music` shows `10.66.66.2:18096` |
| HSTS causing issues on HTTP | Browser cached strict-transport-security | Clear HSTS in browser; ensure cert is valid |

* * *

## Maintenance

| Task | Command |
| --- | --- |
| Deploy/update | `ansible-playbook -i inventory/hosts.ini playbooks/vps/deploy-nginx-music.yml` |
| Check nginx status | `ssh tresor-vps 'sudo systemctl status nginx'` |
| View nginx config | `ssh tresor-vps 'cat /etc/nginx/sites-available/music.conf'` |
| Test nginx config | `ssh tresor-vps 'sudo nginx -t'` |
| Check cert expiry | `ssh tresor-vps 'sudo certbot certificates'` |
| Force cert renewal | `ssh tresor-vps 'sudo certbot renew --force-renewal'` |
| View blocked requests | `ssh tresor-vps 'tail -50 /var/log/nginx/jellyfin_blocked.log'` |
| View error log | `ssh tresor-vps 'tail -50 /var/log/nginx/error.log'` |
| Restart nginx | `ssh tresor-vps 'sudo systemctl restart nginx'` |

* * *

## Gotchas

- **Certbot modifies nginx config** — the `--nginx` plugin rewrites the server block during issuance. The Ansible role handles this by rendering the TLS template *after* cert issuance, overwriting certbot's changes with the hardened config.
- **Cert auto-renewal** — certbot installs a systemd timer (`certbot.timer`) that handles renewal automatically. The nginx plugin reloads nginx after renewal.
- **Two Jellyfin instances, separate configs** — don't confuse `jellyfin` (LAN, port 8096) with `jellyfin-music` (WG, port 18096). They have independent databases, users, and playback states.
- **DNS must point directly to VPS** — `music.example.com` needs an A record to `1.2.3.4`, NOT proxied through Cloudflare (orange cloud off). CF proxying would re-introduce the TOS issue.
- **VPS bandwidth** — your-vps-provider CX23 includes 20TB/month. Monitor usage if streaming heavily.

* * *

*Last validated: February 2026* *Document path: `/docu/Tresor/Services/nginx-music/Overview.md`*