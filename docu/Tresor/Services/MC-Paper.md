# Minecraft — Paper server + Velocity proxy + WireGuard VPN

## Overview

Tresor’s Minecraft stack runs as a **two-node system**:

| Component | Host | Network | Purpose |
| --- | --- | --- | --- |
| **Velocity** | VPS (`tresor-vps`) | public port 25565 + WireGuard (10.66.66.1) | Public proxy → Paper |
| **Paper** | Home node (`tresor`) | isolated `mc_net` ↔ `mc_pub` bridge (10.66.66.2) | Actual game world |
| **WireGuard** | VPS ↔ Home | `10.66.66.0/24` private tunnel | Secure transport, bypass CGNAT |

Traffic never touches the public internet directly:

```
Player → Velocity (VPS) → WireGuard → Paper (Tresor)
```

No ports are forwarded on the home router; only the VPS port 25565 is reachable, and even that is UFW-restricted to Tresor’s WG IP.

* * *

## Runtime Profile

| Setting | Value |
| --- | --- |
| **RAM** | 4 GB allocated to Paper by default |
| **Mode** | Offline (auth handled by proxy) |
| **Whitelist** | Enabled — only approved UUIDs allowed |
| **Max players** | 10 (default) |
| **Autosave** | Enabled every 5 minutes |
| **Backups** | Hourly via cron → `/mnt/data/backups/paper/` |

`server.properties` and `paper-global.yml` are templated by Ansible; runtime tuning (RAM, whitelist) is controlled through group vars.

* * *

## Role Responsibilities

### `roles/paper`

- Spins up rootless container (`ghcr.io/papermc/paper`) under UID/GID 1000.
    
- Attaches only to **`mc_pub`** (bridged to WG network) and **`mc_net`** (backend only).
    
- Templates key configs:
    
    - `server.properties.j2`
        
    - `paper-global.yml.j2`
        
    - `velocity.secret` (sha256 token shared with proxy)
        
- Enforces **offline mode + whitelist only**.
    
- Applies iptables rules in `DOCKER-USER`:
    
    - `ACCEPT` from VPS WG IP
        
    - `DROP` everything else
        
- Includes backup & verify tasks.
    

> **Gotcha:** forwarding secret must come from `vault_velocity_forwarding_secret`.
> If templating uses an alias (`velocity_forwarding_secret | default(vault_velocity_forwarding_secret)`), circular references can break the play — keep only one source of truth.
>
> **RCON password:** `server.properties` renders `paper_rcon_password | default(vault_paper_rcon_password)`. If neither variable is defined Ansible raises `AnsibleUndefinedVariable` at template render time — there is no `CHANGE_ME` fallback. Ensure `vault_paper_rcon_password` is set in vault before deploying with `enable-rcon=true`.

* * *

### `roles/velocity`

- Bare-metal Java service on VPS managed by systemd (`/opt/velocity/velocity.jar`).
    
- Opens `25565/tcp` publicly; **UFW restricts** to `10.66.66.2`.
    
- Forwards players to backend `10.66.66.2:25565`.
    
- Uses `modern` forwarding mode + shared secret for player info pass-through.
    

> **Gotcha:**
> 
> - If the secret mismatch → “Player info forwarding is disabled!”
>     
> - Ensure the service’s working dir (`/opt/velocity/`) contains `velocity.toml` and `servers.toml`.
>     
> - When upgrading Velocity, preserve those configs before replacing the .jar.
>     

* * *

### `roles/wireguard-server` / `roles/wireguard-client`

- Provide the encrypted link between nodes.
    
- Server (`tresor-vps`): `10.66.66.1/24`, listens 51820/udp.
    
- Client (`tresor`): `10.66.66.2/24`, peers → server.
    
- Enables IP forwarding and NAT only for port 25565.
    

> **Gotcha:**
> 
> - Re-apply iptables after reboot — UFW and Docker sometimes flush WG rules.
>     
> - Both roles save persistent keys → `/etc/wireguard/wg0.conf`.
>     

* * *

## Isolation & Security

- **Paper** networked only through WireGuard, unreachable from LAN or WAN.
    
- **Velocity** has zero backend knowledge beyond the forwarding secret.
    
- **No bridging** between `mc_net` / `mc_pub` and any other Docker network.
    
- All MC traffic is end-to-end encrypted (WG) and authenticated (Velocity secret + whitelist).
    
- Backups + logs stored on SSD/HDD; no world data leaves LAN.
    

* * *

## Troubleshooting Quickies

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| Players can’t join | WG tunnel down | `sudo wg show` on both nodes |
| Velocity “disabled forwarding” | Secret mismatch | Re-sync `vault_velocity_forwarding_secret` |
| Lag spikes | RAM cap (4 GB) too low | Raise `paper_memory` var |
| Timeout at join | UFW blocking | Check VPS rules: `sudo ufw status` |
| “Unknown host” in Paper logs | Wrong `server-ip` | Ensure `10.66.66.2` in server.properties |

* * *

This should sit nicely under your `/docs/Services/` folder — self-contained, no deploy steps, all context + gotchas + security model in one place.