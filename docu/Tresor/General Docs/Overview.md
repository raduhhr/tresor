# Overview: Tresor – Self-Hosted, Modular, Secure Homelab

**Tresor** is a fully self-hosted, modular, and automated homelab infrastructure built for personal use, university thesis, and DevOps development. It features complete Docker network separation, a dedicated your-vps-provider VPS, and a local VM mirror (VMM). Everything from provisioning to deployment is handled entirely through Ansible, with full LAN monitoring via Grafana and Prometheus. It is designed around **security**, **extensibility**, and **minimal manual maintenance and full monitoring.**

* * *

## **Core Principles**

- **No-touch:** only OS and SSH set up manually, everything else done via Ansible
- **Everything as Code:** infrastructure & deployments are declarative with playbooks
- **Modular Design:** each component is isolated in its own Ansible role
- **Security-first:** Cloudflare Tunnel, UFW, Fail2Ban, Docker networks separation
- **Reproducible:** Can be redeployed identically on any system

* * *

## **Networking Architecture**

- `mc_net`: isolated, Minecraft server only
- `mc_pub`: wireguard bridge, ensures clients can reach mc_net.  
    <br/>
- `public_net`: internet-facing services via Traefik + Cloudflare Tunnel  
    <br/>
- `internal_net`: East-West access between services (Jellyfin, Filebrowser, Prometheus, Cadvisor, Grafana, etc.)
- `lan_pub`: lan broadcasting network so internal_net containers can be viewed in browser on lan.

> Communication between services is explicitly defined, never assumed.

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

## **Core Services**

| Service | Description | Exposed? | Network |
| --- | --- | --- | --- |
| **Traefik** | Reverse proxy for all web services | ✅   | `public_net` |
| **Cloudflare Tunnel** | Secure tunnel for public exposure | ✅   | —   |
| **MC Server** | On-demand server, cracked allowed | ✅   | `mc_net` |
| ****Uptime Kuma**** | Public MC status page (vps info only) | ✅   | `public_net` |
| ******Landing site (in progress)****** | /devops & /photo (CV devops & gallery subdomains) | ✅   | `public_net` |
| **Grafana** | Monitoring dashboard | ❌   | `internal_net` |
| **Prometheus** | Metrics collector | ❌   | `internal_net` |
| **Jellyfin** | Media server (LAN-only, VLC as client) | ❌   | `internal_net` |
| **File Browser** | Web UI for exploring & managing files | ❌   | `internal_net` |

* * *

## **Security Stack**

- **Cloudflare Tunnel:** no open ports publicly
- **Rate Limiting:** via Traefik middleware
- **Fail2Ban:** brute-force protection (SSH + exposed ports)
- **UFW:** default deny, allow only what is needed
- **Ansible-Vault:** no hardcoded tokens, no tokens published on git.

* * *

## **Users & Access**

- `admin`: main user, no root
- `ansible`: restricted SSH automation user

* * *

## **Documentation & Process**

- **Joplin:** local + exportable documentation
- **Trello:** task management
- **GitHub (Private):**
    - All Ansible roles
    - Shell/Python scripts
    - Config files (sanitized)
- **Thesis:** this project is the foundation of the bachelor's thesis

* * *

## **Future Expansion Plans**

- Scheduled backups via rsync for config files.
- External backup on USB HDD
- CI/CD using GitHub Actions > Ansible
- GitOps via Gitea or Forgejo  
    <br/>

* * *

## Current Status:

Implemented everything, documenting and polishing.

&nbsp;