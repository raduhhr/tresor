# tresor-ctl

Interactive TUI control panel for the Tresor homelab. Wraps Ansible playbooks with live system telemetry, giving you a single interface to monitor and manage all services across the infrastructure.

![Python](../../_resources/python-3.10a78bfa) ![Rich](../../_resources/TUI-rich_20_2B_20questionary-a78.iobadgeTUIrich202B20)

## What it does

`tresor-ctl` connects to both **tresor** (homelab) and **tresor-vps** (your-vps-provider edge) over SSH, pulls live system metrics and container state, and presents a unified dashboard with an interactive service selector. Selecting a service opens its available Ansible playbook actions (deploy, start, stop, restart, backup, etc.) and runs them directly.

```
> admin.circei  //  Tresor control panel

┌─────────────────────────────────────────────────────────┐
│ tresor-vps  1.2.3.4  up 1 day, 22 hours            │
│ ● nginx   ● velocity   ● wg0 (1 minute)                │
│                                                          │
│ cpu  ▏░░░░░░░░░░░░░░░░░░░   4.8%                       │
│ mem  █░░░░░░░░░░░░░░░░░░░   0.6G/3.7G                  │
│                                                          │
│ disk 3.03G/37.2G (9%)                                    │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ tresor   up 1 week, 3 days, 53 minutes                   │
│ ● 12/12 containers   ● wg0 (1 minute)                   │
│                                                          │
│ cpu  ▏░░░░░░░░░░░░░░░░░░░   1.0%                       │
│ mem  ████░░░░░░░░░░░░░░░░   7.3G/31.2G                 │
│                                                          │
│ data 1.92T/7.22T (29%)   ssd 130G/347G (40%) · 447G    │
└─────────────────────────────────────────────────────────┘

  ☁ public  ⌂ internal  ⇄ wg  ⏲ cron
    service              version        state          uptime
> ⌂ filebrowser          v2.59.0        ● running      7h
  ⌂ grafana              12.3.3         ● running      7h
  ⌂ jellyfin             10.11.6        ● running      6h
  ...
  🔧 infrastructure
  🌐 vps
  ⟳  refresh
  ✕  quit
```

## Features

- **Dual-host dashboard** — side-by-side panels for tresor (prod) and tresor-vps (edge) with live CPU, memory, disk, WireGuard status, and container/service health
- **Unified service selector** — single interactive list with network badge, version, state, per-container CPU/mem, and uptime columns
- **Playbook runner** — select a service → pick an action → runs the corresponding `ansible-playbook` command with correct inventory and host targeting
- **Auto-discovery** — services, actions, hosts, and pinned versions are all parsed from the Ansible repo structure (`playbooks/`, `hosts.ini`, `versions.yml`), no hardcoded lists to maintain
- **Infrastructure & VPS submenus** — access to `playbooks/infra/` and `playbooks/vps/` plays (setup-base, deploy-wireguard, backup-all, etc.)
- **SSH resilience** — tries system `ssh` first (respects agent/config), falls back to paramiko; shows clear diagnostics on failure
- **Compose-proof container matching** — handles Docker Compose name prefixes, underscore/hyphen normalization, and substring matching
- **Adaptive layout** — panels render side-by-side on wide terminals, stacked on narrow ones; CPU/mem columns appear when there's room

## Requirements

- Python 3.10+
- SSH access to tresor and tresor-vps (keys loaded in ssh-agent or ~~unencrypted~~)
- Ansible installed (for `ansible-playbook`)

### Python dependencies

```bash
pip install rich questionary paramiko pyyaml --break-system-packages
```

## Setup

1.  Clone or navigate to the Ansible repo:
    
    ```bash
    cd ~/Desktop/tresor/ansible
    ```
    
2.  Ensure your SSH keys are loaded:
    
    ```bash
    # If your key has a passphrase
    eval "$(ssh-agent -s)"
    ssh-add ~/.ssh/id_ed25519_homelab
    ssh-add ~/.ssh/id_ed25519_homelab_vps
    ```
    
    To persist across sessions, add to `~/.bashrc`:
    
    ```bash
    if [ -z "$SSH_AUTH_SOCK" ]; then
        eval "$(ssh-agent -s)" > /dev/null
        ssh-add ~/.ssh/id_ed25519_homelab 2>/dev/null
        ssh-add ~/.ssh/id_ed25519_homelab_vps 2>/dev/null
    fi
    ```
    
3.  Verify Ansible can reach hosts:
    
    ```bash
    ansible all -i inventory/hosts.ini -m ping
    ```
    
4.  Run:
    
    ```bash
    python3 tresor-ctl.py
    ```
    

## Usage

### Main screen

Arrow keys to navigate, Enter to select. The service list shows:

| Column | Source |
| --- | --- |
| Badge | Network zone from `SVC_META` (☁ ⌂ ⇄ ⏲) |
| Service | Playbook folder name |
| Version | Running container tag or `versions.yml` pinned |
| State | Docker container status or cron/stopped |
| CPU/Mem | Live `docker stats` (when terminal is wide enough) |
| Uptime | Container uptime or time since exit |

### Service actions

Selecting a service shows its available playbooks in logical order:

```
deploy → start → stop → restart → status → verify → backup → update → remove
```

Actions are discovered from `playbooks/<service>/*.yml` — add a new YAML file and it appears automatically.

### Infrastructure plays

The 🔧 infrastructure option exposes `playbooks/infra/` plays:

- `setup-base` — OS hardening, packages, firewall, SSH, fail2ban
- `setup-docker` — Docker daemon, networks, compose
- `setup-networks` — Docker network segmentation
- `deploy-wireguard` — WireGuard tunnel to VPS
- `backup-all` — Full service backup sweep
- `status-all` — Health check across all services
- `verify-*` — Verification plays for base, docker, networks, wireguard

### VPS plays

The 🌐 vps option exposes `playbooks/vps/` plays:

- `setup-base` — VPS OS hardening
- `setup-wireguard` — WireGuard server endpoint
- `setup-nginx-music` — Nginx reverse proxy for Jellyfin Music
- `setup-velocity` — Minecraft Velocity proxy

### Host targeting

Playbooks that declare `hosts: prod` or `hosts: tresor` run against the correct host automatically. Playbooks with `hosts: all` prompt you to pick a target from the inventory.

## How it works

### Data collection

On each refresh, tresor-ctl opens SSH connections to both hosts and runs a bash probe script that collects:

| Metric | Source |
| --- | --- |
| CPU | `/proc/stat` delta (0.25s sample) |
| Memory | `/proc/meminfo` |
| Disk | `lsblk -b` + `df -B1` |
| Containers | `docker ps -a` |
| Per-container metrics | `docker stats --no-stream` |
| WireGuard | `wg show wg0` |
| VPS services | `systemctl is-active nginx/velocity` |

All parsing uses `/proc` directly with `LC_ALL=C` to avoid locale issues. The script is sent via `bash -s` to avoid depending on the remote user's default shell.

### Version resolution

Versions are resolved with this priority:

1.  Running container image tag (from `docker ps`)
2.  Pinned version from `inventory/group_vars/prod/versions.yml`
3.  `v0` for own scripts (bday-notifier, steam-free-notifier)

### SSH connection strategy

```
1. System ssh (BatchMode=yes) — uses ~/.ssh/config, agent, ProxyJump, etc.
2. Paramiko with ssh-agent  — allow_agent=True, look_for_keys=True
3. Paramiko with explicit key — direct key file, no agent
```

If all fail, the panel shows the exact error and suggested fix.

## File structure

```
ansible/
├── tresor-ctl.py              ← this tool
├── inventory/
│   ├── hosts.ini              ← host discovery (prod/qa/vps)
│   └── group_vars/
│       └── prod/
│           └── versions.yml   ← pinned image versions
├── playbooks/
│   ├── <service>/             ← auto-discovered services
│   │   ├── deploy.yml
│   │   ├── start.yml
│   │   ├── stop.yml
│   │   └── ...
│   ├── infra/                 ← infrastructure plays
│   └── vps/                   ← VPS setup plays
└── roles/                     ← Ansible roles (used by playbooks)
```

## Configuration

All config is discovered from the Ansible repo — no separate config file needed. Key touchpoints:

| What | Where |
| --- | --- |
| Hosts & IPs | `inventory/hosts.ini` |
| SSH keys | `[all:vars]` and `[vps:vars]` in hosts.ini |
| Pinned versions | `inventory/group_vars/prod/versions.yml` |
| Service metadata | `SVC_META` dict in tresor-ctl.py |
| Skipped folders | `SKIP_SERVICES` set in tresor-ctl.py |
| Color palette | `C_*` constants in tresor-ctl.py |

### Adding a new service

1.  Create the role in `roles/<service>/`
2.  Create playbooks in `playbooks/<service>/` (deploy.yml, start.yml, etc.)
3.  Add an entry to `SVC_META` in tresor-ctl.py with network zone and description
4.  Add the image to `versions.yml` if it's a Docker service
5.  The service appears automatically on next run