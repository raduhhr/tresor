# Architecture

Tresor is a small operations platform rather than a single app. The design goal
is to keep public ingress narrow while still making daily operations visible.

## Boundaries

| Boundary | Role |
| --- | --- |
| Public Internet | Browsers, Minecraft clients, selected live status/product pages |
| VPS edge | nginx, WireGuard server, Velocity proxy, update artifact staging |
| Home node | Docker workloads, monitoring, data products, private services |
| QA VM | Rehearsal target for role and playbook changes |
| Recovery layer | Local backups plus selected R2 copies for small service state |

## Network Model

Public web traffic is split by intent:

- Cloudflare Tunnel publishes selected HTTP services without opening the home
  router.
- VPS nginx proxies selected services over WireGuard.
- Velocity exposes one Minecraft TCP entry point and forwards to the private
  Paper backend.

Docker networks divide service classes:

| Network class | Purpose |
| --- | --- |
| `public_net` | Edge-facing web services behind Cloudflare/Traefik |
| `internal_net` | Grafana, Prometheus, databases, app-to-app traffic |
| `mc_net` | Isolated game backend |
| `lan_pub` | LAN-published internal tools |
| `wg0` | Host-level private path between home and VPS |

## Data Products

Tresor Index acts as the archive layer for sources that would otherwise become
one-off scripts. It stores source definitions, fetch runs, items, versions,
observations, quarantine records, and alert events. It also powers internal
Grafana dashboards and the private API bridge used by vot-parlament.ro.

![Tresor Index runtime](assets/grafana-index-runtime.png)

## Public Product Support

The infrastructure now includes support for:

- vot-parlament.ro frontend deployment and API routing.
- BatchYT self-hosted update artifacts.
- Plane watcher public site plumbing.
- Scheduled satellite capture and operator tooling.

Those products may have their own closed or separate repositories; this repo
documents the shared operations layer.
