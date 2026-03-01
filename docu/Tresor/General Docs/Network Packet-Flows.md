# 🌐 Tresor – Network Packet Flows (Updated October 2025)

**explicit, least-privilege connectivity**

* * *

## High-Level Topology (ASCII Diagram)

```
        _____________________Internet                             
        |                       │					 lan_pub (LAN bridge)
        |             Cloudflare Tunnel (HTTPS 443)                      ────────────────────
        |                       │                                                │
        |                       |                                                │
        |                    Traefik  (HTTP)                            internal_net (LAN-only)
        |                       │                                       ───────────────────────
        |                  public_net                                    • Jellyfin
        |               (exposed via CF)                                 • FileBrowser
        |              ─────────────────                                 • Grafana
        |              • Uptime Kuma                                     • Prometheus
        |           
        |                                
        |
Velocity MC Proxy-----------------------------------------|
──────────────────────────                                |
• your-vps-provider VPS (WireGuard Server 10.66.66.1)               |
• Public 25565 / UFW protected                            |
                                                          |
                                            mc_pub (WireGuard Client Iface)
                                            ─────────────────────────────
                                            • bridge → mc_net (PaperMC)
                                                           │
                                                           ▼
                                                mc_net (isolated backend)
                                                ─────────────────────────
                                                • PaperMC (Docker)
                                                • whitelist-only, offline             
```

* * *

## Core Docker Networks (Tresor)

| Network | Scope | Purpose | Typical Services |
| --- | --- | --- | --- |
| **mc_net** | Isolated | Minecraft backend (Paper) | Paper server only |
| **public_net** | Internet-facing | Public web exposure via Cloudflare Tunnel + Traefik | Traefik, Cloudflared, MC Frontend, Uptime Kuma, Landing Site |
| **internal_net** | LAN-only | Local dashboards / media | Jellyfin, Portainer, Grafana, Prometheus, Syncthing, File Browser |

> **Rule:** Communication between networks is *explicitly defined — never assumed.*

* * *

## External / Hybrid Links

### `wireguard`

Point-to-point VPN between **Tresor ↔ VPS**

| Side | Host | Role | Address | Purpose |
| --- | --- | --- | --- | --- |
| VPS | `tresor-vps` | Public edge | `10.66.66.1` | Hosts Velocity proxy, forwards internet traffic |
| Tresor | `tresor` | Private backend | `10.66.66.2` | Hosts Paper server backend |

- Encrypted UDP tunnel (`51820/udp`) carrying **all Minecraft traffic**
- No other ports exposed publicly on either side
- **UFW** restricts inbound to: `22/tcp`, `51820/udp`, `25565/tcp` (VPS only)

* * *

## Packet-Level Flows

&nbsp;

### 🎮 Minecraft Connection Flow

```
Player (Internet)
    ↓ TCP 25565
VPS (tresor-vps) — Velocity Proxy
    ↓ WireGuard tunnel (UDP 51820)
    ↓ 10.66.66.1 → 10.66.66.2
Tresor — Paper Server (Docker container on mc_net)
    ↓ bound to 10.66.66.2:25565
    ↓ DOCKER-USER chain: ACCEPT 10.66.66.1 → DROP others
```

**Security Layers**

- VPS UFW: allows only 51820/udp & 25565/tcp
- WireGuard: encrypted tunnel for game traffic
- Tresor UFW: allows WireGuard subnet (10.66.66.0/24)
- DOCKER-USER: `ACCEPT 10.66.66.1`, `DROP all else`
- Paper: `online-mode=false`, whitelist enforced

* * *

### Web Service Flow

```
Internet
    ↓ HTTPS (443)
Cloudflare Edge
    ↓ Cloudflare Tunnel → Tresor (no open ports)
Cloudflared container (public_net)
    ↓ HTTP (80)
Traefik (public_net)
    ↓ hostname routing
Service container (public_net or internal_net)
```

#### Port Mapping Table

| Service | Host Port | Container Port | Network | Exposed? |
| --- | --- | --- | --- | --- |
| **Traefik** | 80 (local) | 80  | public_net | via Cloudflare Tunnel |
| **Grafana** | 3000 | 3000 | internal_net | LAN only |
| **Prometheus** | 9090 | 9090 | internal_net | LAN only |
| **Jellyfin** | 8096 | 8096 | internal_net | LAN only |
| **File Browser** | 8080 | 80  | internal_net | LAN only |
| **Paper (MC)** | —   | 25565 | mc_net | via WireGuard only |

* * *

## Security Summary

- **Cloudflare Tunnel** → only ingress for all web apps
- **WireGuard** → sole bridge between VPS and Tresor
- **UFW + Fail2Ban** → default-deny + brute-force protection on both hosts
- **No Docker bridge exposure** — containers only on private overlays
- **No password SSH logins** — key-only (`ansible user`)
- **DOCKER-USER** rules persist to enforce cross-network firewalls

* * *

*Last validated: October 2025*  
*Document path: `/docu/Tresor/Networking/Packet-Flows.md`*