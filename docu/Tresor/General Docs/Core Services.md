# Core Services 

Tresor and its public VPS now form a **two-tier Minecraft and web infrastructure**:

- **VPS (`tresor-vps`)** → lightweight public edge (Velocity + WireGuard + UFW)
- **Tresor (on-prem)** → full Docker-based homelab with Paper, Traefik, and internal services

* * *

## Public-facing (`public_net`)

| Service | Purpose | Notes |
| --- | --- | --- |
| **Traefik** | Reverse proxy for all HTTP(S) services (TLS, rate-limit, headers) | Handles all ingress from Cloudflare Tunnel |
| **Cloudflare Tunnel** | Secure public exposure for web apps (no direct ports open) | Cloudflare → Tresor, bypasses router/NAT |
| **Uptime Kuma** | Public status page | Monitors all services (LAN + public) |
| **Landing Site** | `/devops` and `/photo` — personal CV + gallery | Static site served via Traefik & CF Tunnel |

> **No TCP game traffic passes through Cloudflare Tunnel.**  
> Minecraft access is handled separately via Velocity on the VPS.

* * *

## External (VPS – `wireguard`)

| Service | Host | Purpose | Exposed | Notes |
| --- | --- | --- | --- | --- |
| **Velocity (Minecraft Proxy)** | `tresor-vps` | Public entrypoint for all Minecraft players | ✅ : 25565 /tcp | Runs natively via `systemd`; forwards to `10.66.66.2:25565` (Paper) over WireGuard |
| **WireGuard daemon** | `tresor-vps` + `tresor` | Encrypted tunnel between VPS ↔ homelab | ✅ : 51820 /udp | All MC traffic and control RPCs flow through this tunnel |
| **UFW + Fail2Ban** | `tresor-vps` | Host-level security | ✅   | Default-deny, allow SSH + WG + Velocity only |

* * *

## Internal-only (`internal_net`)

| Service | Purpose | Notes |
| --- | --- | --- |
| **Grafana** | Monitoring dashboard | Visualizes Prometheus metrics |
| **Prometheus** | Metrics collector | Polls internal/exporter endpoints |
| **Cadvisor** | Container metrics | logs container data and exposes it as endpoint |
| **Node Exporter** | Host metrics | logs host data and exposes it as endpoint |
| **Jellyfin** | Media server | Used for music+video streaming, phone app and web client. |
| **File Browser** | File explorer UI | RW for `/mnt/data` shares, web client |

* * *

## Isolated (`mc_net`)

| Service | Purpose | Exposed | Notes |
| --- | --- | --- | --- |
| **Paper (Minecraft Server)** | Core backend server (whitelist-only) | ✅ (via WireGuard → VPS) | Runs in Docker on Tresor, bound to `10.66.66.2:25565`; receives all traffic from Velocity (VPS) |

&nbsp;

* * *

##  Notes

- **Velocity** on VPS is the *only* service with a public TCP port (25565).
- **Paper MC** is reachable **only** through the WireGuard tunnel (`10.66.66.1 ↔ 10.66.66.2`).
- **All web exposure** uses **Cloudflare Tunnel → Traefik** (no open ports).
- **UFW + Fail2Ban** protect both VPS and Tresor.
- **No root logins**, **SSH key-only**, **Docker** wherever possible.

* * *

*This layout minimizes attack surface, isolates game traffic from web services,  
and keeps the Tresor homelab completely non-public while still providing  
controlled, secure access for friends or admin workflows.*