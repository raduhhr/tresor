# Tresor: Self-hosted homelab infrastructure: Docker, Ansible (22 roles, 135+ playbooks), WireGuard, Cloudflare Tunnel, Prometheus/Grafana

Tresor is a fully self-hosted, modular, and automated homelab infrastructure built for personal use and DevOps development.
It features complete Docker network separation, a dedicated VPS edge node, WireGuard tunneling, and a local KVM sandbox.

Everything from provisioning to deployment is handled entirely through Ansible (22 roles, 135+ playbooks), with full LAN monitoring via Grafana and Prometheus.  
Designed around security, extensibility, and minimal manual maintenance.


---

## Core Principles

- **No-touch:** only OS and SSH set up manually; everything else via Ansible
- **Everything as Code:** infrastructure and deployments are fully declarative
- **Modular Design:** each component isolated in its own Ansible role
- **Security-first:** Cloudflare Tunnel, WireGuard, Fail2Ban, Docker network separation, LAN-only bind addresses
- **Reproducible:** can be redeployed identically on any system

---

## Infrastructure

Three hosts, three environments:

| Host | Environment | Description |
|------|-------------|-------------|
| **tresor** | prod | Home Docker host — runs all services, 192.168.0.0/24 LAN |
| **tresor-vm** | qa | KVM sandbox for testing roles before prod |
| **tresor-vps** | vps | VPS — WireGuard server, Velocity MC proxy, nginx reverse proxy |

---

## Ansible Automation

22 roles and 135+ playbooks with consistent conventions across every service.

**Playbook lifecycle per service:** `deploy` · `remove` · `backup` · `restore` · `backup-test` · `start` · `stop` · `restart` · `status` · `update`

**Key conventions:**
- Config dirs on SSD: `/mnt/ssd/configs/<service>/`
- Backup dirs: `/mnt/data/files/Backups/<service>/`
- Backup naming: `<service>-backup-DDMMYYYY-HHMM.tar.gz` with 30-day automatic pruning
- Version pinning: centralized in `group_vars/prod/versions.yml` via `tresor_versions` dict — never hardcoded in roles
- Secrets: Ansible Vault with per-environment identity labels (prod, qa, vps) — zero tokens in Git
- Variable hierarchy: `ansible.cfg` → `group_vars/all` → `group_vars/{prod,qa,vps}` → `host_vars` → role defaults

```
roles/
├── base/                  # System hardening, users, SSH, Fail2Ban, UFW, sysctl, unattended-upgrades
├── docker/                # Docker CE install + daemon config
├── networks/              # All 5 Docker networks
├── wireguard-client/      # WG client on tresor (10.66.66.2)
├── wireguard-server/      # WG server on VPS (10.66.66.1)
├── motd/                  # Dynamic SSH welcome banner
├── traefik/               # Reverse proxy + TLS + rate-limiting middleware
├── cloudflared/           # Cloudflare Tunnel
├── grafana/               # Monitoring dashboard
├── prometheus/            # Metrics (+ node-exporter, cAdvisor)
├── jellyfin/              # Media server (movies, shows, photos)
├── jellyfin-music/        # Music-only instance (WG-bound :18096)
├── filebrowser/           # Personal file management UI
├── filebrowser-public/    # Friends 1TB file drop (WG-bound :8082)
├── uptime-kuma/           # MC status page
├── kiwix/                 # Offline Wikipedia
├── paper/                 # Minecraft server
├── velocity/              # MC proxy (VPS, systemd)
├── nginx-music/           # Reverse proxy for music + cloud subdomains (VPS)
├── content-notifier/      # Discord alerts for new Jellyfin media
├── bday-notifier/         # Birthday bot (cron + Discord)
└── steam-free-notifier/   # Steam free game alerts (cron + Discord)
```
## tresor-ctl

A Python TUI control panel that auto-discovers services from the `playbooks/` directory structure.  
Provides a terminal dashboard for running lifecycle actions (deploy, start, stop, restart, status, backup, update, remove, etc.) against any service without memorizing playbook paths.

Built with Rich + Questionary + Paramiko for live SSH interaction.

<img width="1238" height="1648" alt="image" src="https://github.com/user-attachments/assets/328398f1-f89a-4a43-b52b-bc50bc2f6d42" />
<img width="1274" height="562" alt="image" src="https://github.com/user-attachments/assets/92e58eb4-0145-4dc9-844c-7c5b67a562cd" />



---

## Networking Architecture

Five isolated Docker networks enforce strict traffic boundaries:

| Network | Purpose | Services |
|---------|---------|----------|
| `public_net` | Internet-facing via Cloudflare Tunnel + Traefik | Traefik, Cloudflared, Uptime Kuma, FileBrowser Public |
| `internal_net` | LAN-only east–west traffic | Grafana, Prometheus, Jellyfin, Jellyfin Music, FileBrowser, Kiwix |
| `mc_net` | Isolated Minecraft backend | PaperMC |
| `mc_pub` | WireGuard bridge (VPS ↔ MC backend) | PaperMC egress |
| `lan_pub` | LAN broadcast bridge | FileBrowser, Kiwix |

```
         _____________________ Internet
         |                       │
         |             Cloudflare Tunnel (443)
         |                       │
         |                    Traefik (HTTP)                       internal_net (LAN-only, 192.168.1.100)
         |                       │                                 ─────────────────────────────────────
         |                  public_net                              • Jellyfin        :8096
         |               (exposed via CF)                           • FileBrowser     :8080
         |              ─────────────────                           • Grafana         :3000
         |              • Uptime Kuma                               • Prometheus      :9090
         |                                                          • Kiwix           :8181
         |
  VPS (WireGuard Server, 10.66.66.1)
  ───────────────────────────────────
  • nginx: music.example.com (:443)  → WG → Jellyfin Music  (10.66.66.2:18096)
  • nginx: cloud.example.com (:443)  → WG → FileBrowser Pub (10.66.66.2:8082)
  • Velocity MC proxy      (:25565)  → WG → PaperMC         (10.66.66.2:25565)
         |
         |                                        mc_pub (WireGuard bridge)
  Velocity MC Proxy ─────────────────────────────────────────────────|
                                                                     │
                                                            mc_net (isolated backend)
                                                           ─────────────────────────
                                                            • PaperMC (Docker)
                                                            • whitelist-only, offline
```

---

## Services

### Docker Containers (tresor — prod)

| Service | Description | Exposed? | Network | Access |
|---------|-------------|----------|---------|--------|
| **Traefik** | Reverse proxy for all web services | Yes | `public_net` | Via Cloudflare Tunnel |
| **Cloudflared** | Secure Cloudflare Tunnel ingress | Yes | `public_net` | — |
| **Uptime Kuma** | Public MC status page | Yes | `public_net` | mc-status.example.com |
| **PaperMC** | Minecraft server (offline-mode, whitelist) | Yes | `mc_net` / `mc_pub` | VPS Velocity → WG |
| **Jellyfin Music** | Music-only Jellyfin instance | Yes | `internal_net` | music.example.com (VPS nginx → WG :18096) |
| **FileBrowser Public** | 1 TB file drop for friends | Yes | `public_net` | cloud.example.com (VPS nginx → WG :8082) |
| **Grafana** | Monitoring dashboard | No | `internal_net` | LAN :3000 |
| **Prometheus** | Metrics collector | No | `internal_net` | LAN :9090 |
| **Node Exporter** | Host-level metrics | No | `internal_net` | Pulled by Prometheus |
| **cAdvisor** | Docker container metrics | No | `internal_net` | Pulled by Prometheus |
| **Jellyfin** | Media server (movies, shows, photos) | No | `internal_net` | LAN :8096 |
| **FileBrowser** | Personal file management UI | No | `internal_net` / `lan_pub` | LAN :8080 |
| **Kiwix** | Offline Wikipedia (110 GB ZIM) | No | `internal_net` / `lan_pub` | LAN :8181 |

### Cron & Notification Bots (tresor — prod)

| Service | Description | Schedule |
|---------|-------------|----------|
| **content-notifier** | Discord alerts when new media lands in Jellyfin libraries | Cron |
| **steam-free-notifier** | Discord alerts for free Steam games | Cron |
| **bday-notifier** | Birthday reminder bot via Discord | Cron |

### VPS Services (systemd, not Docker)

| Service | Description |
|---------|-------------|
| **Velocity** | Minecraft proxy — accepts public :25565 and forwards to tresor over WG |
| **nginx** | Reverse proxy for music.example.com and cloud.example.com → WG tunnel |

---

## Monitoring Stack

All components operate **LAN-only** — no external exposure.  
Data flows one way: metrics are pulled internally; there are no WAN-bound pushes or telemetry.

```
[Node Exporter]     [cAdvisor]
       │                   │
       └─────> Prometheus ◄┘
                    │
                    ▼
                 Grafana
```

**Grafana Host dashboard**  
<img width="2518" height="1134" alt="image" src="https://github.com/user-attachments/assets/82020718-73a6-4db3-9395-00c39d3d4963" />

**Grafana Containers dashboard**  
<img width="2478" height="1148" alt="image" src="https://github.com/user-attachments/assets/4f90e18d-2bd4-4104-81b5-6bc8362da8f1" />


**Jellyfin libraries**  
<img width="1223" height="617" alt="image" src="https://github.com/user-attachments/assets/f4501273-74a7-4d05-ab1c-a14875358324" />


**FileBrowser tree**  
<img width="2525" height="1053" alt="image" src="https://github.com/user-attachments/assets/c86f3943-5db0-43f5-a5f4-2a8ad2746f9b" />


---

## Security

- **Zero public ports on tresor** — all public traffic enters via Cloudflare Tunnel or WireGuard
- **Cloudflare Tunnel** → Traefik for HTTPS services, no open inbound ports
- **WireGuard** → encrypted tunnel between VPS and tresor
- **UFW** → default deny, allowlisted per-service with /24 CIDRs
- **Fail2Ban** → brute-force protection on SSH and exposed services
- **Docker bind addresses** → LAN services bind to LAN IP (not 0.0.0.0), WG services bind to WireGuard IP
- **DOCKER-USER iptables** → tightened to /24 CIDR for LAN allowlisting
- **Node Exporter / cAdvisor** → no published host ports, internal_net only
- **Ansible Vault** → per-environment encrypted secrets, zero tokens in Git
- **SSH hardening** → key-only auth, no root login, custom sshd config

---

## Backup Strategy

Automated via Ansible playbooks with a consistent pattern across all stateful services.

**Backup cycle:**

1. Stop container (ensures data consistency)
2. Archive config directory → `tar.gz` with timestamped filename
3. Start container
4. Log operation with ISO 8601 timestamp to `/var/log/<service>-backup.log`
5. Prune backups older than 30 days

A `backup-all.yml` infra playbook runs backups across all services sequentially.

**Restore playbooks** for every service follow a safe sequence: validate tarball → pre-restore safety snapshot → stop & remove container → wipe data directory → extract backup → fix ownership → redeploy via role. Each restore supports auto-picking the latest backup or targeting a specific snapshot via `-e backup_file=`.

**Backup verification** via `backup-test.yml` playbooks for critical stateful services (Paper, Grafana, Prometheus, Uptime Kuma, Jellyfin, Jellyfin Music). Each test runs the full lifecycle — fresh backup → fingerprint data (DB hashes, file counts) → destroy → restore → redeploy → compare fingerprints — proving backup integrity end-to-end.

---

## Users & Access

- `admin` / `mainuser`: primary account, no root login
- `ansible`: restricted SSH automation user (key-only, sudoers)

---

## Documentation & Process

- **Joplin** for local documentation
- **Trello** for task tracking
- **GitHub (Public, sanitized)** for all roles, scripts, and configs

---

## Status

Fully deployed and continuously monitored.  
All components provisioned through Ansible, containerized under Docker, and secured via Cloudflare Tunnel + WireGuard.  

**status-all playbook output**  
Press any key to continue...
 infrastructure   status all

  ────────────  infra → status-all  @ homelab-node  ────────────
  $ ansible-playbook -i inventory/hosts.ini playbooks/infra/status-all.yml


PLAY [Homelab — status on steroids] ********************************************

TASK [collect | system] ********************************************************
ok: [homelab-node]

TASK [collect | storage] *******************************************************
ok: [homelab-node]

TASK [collect | network] *******************************************************
ok: [homelab-node]

TASK [collect | clock & ntp] ***************************************************
ok: [homelab-node]

TASK [collect | security] ******************************************************
ok: [homelab-node]

TASK [collect | docker engine] *************************************************
ok: [homelab-node]

TASK [collect | containers] ****************************************************
ok: [homelab-node]

TASK [collect | prometheus targets (API)] **************************************
ok: [homelab-node]

TASK [collect | service access map] ********************************************
ok: [homelab-node]

TASK [══════════════════════ SYSTEM ══════════════════════════════════════] ****
ok: [homelab-node] =>
  msg: |2-
      Hostname:      homelab-node
      OS:            Debian GNU/Linux 12 (bookworm)
      Kernel:        6.1.x-amd64  [x86_64]
      Uptime:        17d 17h
      Load avg:      0.08 0.08 0.08  (1m 5m 15m)
      Processes:     673 total

      ── CPU ─────────────────────────────────────────────────────────
      CPU(s):                                                       8
      Model name:                                               Intel(R) Core(TM) CPU
      Thread(s) per core:                               2
      Core(s) per socket:                               4
      CPU scaling:                                      68%
      CPU max MHz:                                             4200.0000

      ── Memory ──────────────────────────────────────────────────────
                     total        used        free      shared  buff/cache   available
      Mem:             33G        8.2G        565M        268M         25G         25G
      Swap:           8.4G        519M        7.9G

TASK [══════════════════════ STORAGE ═════════════════════════════════════] ****
ok: [homelab-node] =>
  msg: |2-
      ── Disk mounts ─────────────────────────────────────────────────
      Filesystem      Size  Used Avail Use% Mounted on
      /dev/sdX1        92G  3.5G   84G   5% /
      /dev/sdX3       347G  124G  206G  38% /srv/ssd
      /dev/sdX2       488M  5.9M  482M   2% /boot/efi
      /dev/sdY1       7.3T  2.1T  4.9T  30% /srv/data
      /dev/loop0     1007G  3.6M  957G   1% /srv/data/cloud

      ── Docker space ────────────────────────────────────────────────
      TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
      Images          16        11        5.246GB   880MB (16%)
      Containers      13        13        3.191MB   0B (0%)
      Local Volumes   19        19        515.8MB   492.5MB (95%)
      Build Cache     0         0         0B        0B

TASK [══════════════════════ NETWORK ═════════════════════════════════════] ****
ok: [homelab-node] =>
  msg: |2-
      ── Interfaces (IPv4) ───────────────────────────────────────────
      lo               UNKNOWN        127.0.0.1/8
      enp1s0           UP             192.168.x.x/24
      wg0              UNKNOWN        10.x.x.x/24
      br-public_net    UP             172.20.0.1/24
      br-internal_net  UP             172.21.0.1/24
      docker0          UP             172.17.0.1/16
      br-lan_pub       UP             172.22.0.1/24

      ── WireGuard ───────────────────────────────────────────────────
      interface: wg0
        public key: <REDACTED_PUBLIC_KEY>
        private key: (hidden)
        listening port: <WG_PORT>

      peer: <REDACTED_PEER_PUBLIC_KEY>
        preshared key: (hidden)
        endpoint: <REDACTED_ENDPOINT>
        allowed ips: <REDACTED_ALLOWED_IPS>
        latest handshake: <HEALTHY>
        transfer: <REDACTED_TRANSFER_STATS>
        persistent keepalive: every 25 seconds

      ── Listening ports ─────────────────────────────────────────────
      State  Recv-Q Send-Q       Local Address:Port  Peer Address:PortProcess
      LISTEN 0      4096          192.168.x.x:3000       0.0.0.0:*    users:(("docker-proxy",pid=PID,fd=FD))
      LISTEN 0      4096          192.168.x.x:8096       0.0.0.0:*    users:(("docker-proxy",pid=PID,fd=FD))
      LISTEN 0      4096          192.168.x.x:8080       0.0.0.0:*    users:(("docker-proxy",pid=PID,fd=FD))
      LISTEN 0      4096          192.168.x.x:8181       0.0.0.0:*    users:(("docker-proxy",pid=PID,fd=FD))
      LISTEN 0      4096             127.0.0.1:8086      0.0.0.0:*    users:(("docker-proxy",pid=PID,fd=FD))
      LISTEN 0      4096          192.168.x.x:9090       0.0.0.0:*    users:(("docker-proxy",pid=PID,fd=FD))
      LISTEN 0      4096             10.x.x.x:8082       0.0.0.0:*    users:(("docker-proxy",pid=PID,fd=FD))
      LISTEN 0      4096            10.x.x.x:18096       0.0.0.0:*    users:(("docker-proxy",pid=PID,fd=FD))
      LISTEN 0      128                0.0.0.0:22        0.0.0.0:*    users:(("sshd",pid=PID,fd=FD))
      LISTEN 0      4096      [::ffff:10.x.x.x]:25565          *:*    users:(("java",pid=PID,fd=FD))
      LISTEN 0      128                   [::]:22           [::]:*    users:(("sshd",pid=PID,fd=FD))

TASK [══════════════════════ CLOCK & NTP ═════════════════════════════════] ****
ok: [homelab-node] =>
  msg: |2-
                     Local time: <SANITIZED>
                 Universal time: <SANITIZED>
                       RTC time: <SANITIZED>
                      Time zone: UTC
      System clock synchronized: yes
                    NTP service: active
                RTC in local TZ: no

      ── Timesync detail ─────────────────────────────────────────────
             Server: pool.ntp.org
      Poll interval: 34min 8s (min: 32s; max 34min 8s)
               Leap: normal
            Version: 4
            Stratum: 4
          Reference: <REDACTED>
          Precision: 1us (-24)
      Root distance: <REDACTED>
             Offset: <REDACTED>
              Delay: <REDACTED>
             Jitter: <REDACTED>

TASK [══════════════════════ SECURITY ════════════════════════════════════] ****
ok: [homelab-node] =>
  msg: |2-
      ── Firewall: INPUT ─────────────────────────────────────────────
      Chain INPUT (policy DROP)
      num  target     prot opt source               destination
      1    ufw-before-logging-input  0    --  0.0.0.0/0            0.0.0.0/0
      2    ufw-before-input          0    --  0.0.0.0/0            0.0.0.0/0
      3    ufw-after-input           0    --  0.0.0.0/0            0.0.0.0/0
      4    ufw-after-logging-input   0    --  0.0.0.0/0            0.0.0.0/0
      5    ufw-reject-input          0    --  0.0.0.0/0            0.0.0.0/0
      6    ufw-track-input           0    --  0.0.0.0/0            0.0.0.0/0
      7    DROP       6    --  0.0.0.0/0            0.0.0.0/0            tcp dpt:25565 /* Drop others to Paper */
      8    ACCEPT     6    --  192.168.x.0/24       0.0.0.0/0            tcp dpt:8181  /* Kiwix (LAN) */

      ── Firewall: DOCKER-USER ───────────────────────────────────────
      Chain DOCKER-USER (1 references)
      num  target     prot opt source               destination
      1    ACCEPT     6    --  10.x.x.1            0.0.0.0/0             tcp dpt:25565 /* Allow VPS to Paper */
      2    DROP       6    --  0.0.0.0/0           0.0.0.0/0             tcp dpt:25565 /* Drop others to Paper */
      3    RETURN     0    --  0.0.0.0/0           0.0.0.0/0

      ── Fail2Ban: sshd jail ─────────────────────────────────────────
      Status for the jail: sshd
      |- Filter
      |  |- Currently failed:       0
      |  |- Total failed:           0
      |  `- Journal matches:        _SYSTEMD_UNIT=sshd.service + _COMM=sshd
      `- Actions
         |- Currently banned:       0
         |- Total banned:           0
         `- Banned IP list:

TASK [══════════════════════ DOCKER ENGINE ═══════════════════════════════] ****
ok: [homelab-node] =>
  msg: |2-
      ── Engine ──────────────────────────────────────────────────────
       Version:           28.x
       API version:       1.5x
       Built:             <SANITIZED_BUILD_DATE>
       OS/Arch:           linux/amd64

      ── Info ────────────────────────────────────────────────────────
      Data root:       /srv/ssd/containers
      Containers:      13 total  (13 running, 0 stopped, 0 paused)
      Images:          16
      Logging drv:     journald
      Cgroup drv:      systemd
      Security:        ["name=apparmor","name=seccomp,profile=builtin","name=cgroupns"]

      ── Networks ────────────────────────────────────────────────────
      bridge        bridge  local  <NETWORK_ID>
      host          host    local  <NETWORK_ID>
      internal_net  bridge  local  <NETWORK_ID>
      lan_pub       bridge  local  <NETWORK_ID>
      none          null    local  <NETWORK_ID>
      public_net    bridge  local  <NETWORK_ID>

      ── Volumes ─────────────────────────────────────────────────────
      19 local volumes present under /srv/ssd/containers/volumes
      volume names and IDs redacted for public output

TASK [══════════════════════ CONTAINERS ══════════════════════════════════] ****
ok: [homelab-node] =>
  msg: |2-
      ST  NAME                     IMAGE                                    UPTIME                 PORTS
      ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ✔   cadvisor                 gcr.io/cadvisor/cadvisor:vX.Y.Z          4 hours ago
        ↳ restart=unless-stopped  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

      ✔   cloudflared              cloudflare/cloudflared:20XX.X.X          4 months ago           127.0.0.1:8086->8086/tcp
        ↳ restart=always  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

      ✔   filebrowser-public       filebrowser/filebrowser:vX.Y.Z           6 days ago             10.x.x.x:8082->80/tcp
        ↳ bind  /srv/config/filebrowser-public → /config (rw)
        ↳ bind  /srv/data/cloud → /srv (rw)
        ↳ restart=unless-stopped  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

      ✔   filebrowser              filebrowser/filebrowser:vX.Y.Z           3 hours ago            192.168.x.x:8080->80/tcp
        ↳ bind  /srv/config/filebrowser → /config (rw)
        ↳ bind  /srv/data/files → /srv (rw)
        ↳ restart=unless-stopped  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

      ✔   grafana                  grafana/grafana:12.x                     4 hours ago            192.168.x.x:3000->3000/tcp
        ↳ bind  /srv/config/grafana → /etc/grafana + /var/lib/grafana
        ↳ restart=unless-stopped  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

      ✔   jellyfin-music           jellyfin/jellyfin:10.x                   7 days ago             10.x.x.x:18096->8096/tcp
        ↳ bind  /srv/config/jellyfin-music → /config (rw)
        ↳ bind  media libraries → /media/* (ro)
        ↳ restart=unless-stopped  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

      ✔   jellyfin                 jellyfin/jellyfin:10.x                   2 days ago             192.168.x.x:8096->8096/tcp
        ↳ bind  /srv/config/jellyfin → /config (rw)
        ↳ bind  /srv/data/files → /media (ro)
        ↳ restart=unless-stopped  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

      ✔   kiwix                    ghcr.io/kiwix/kiwix-serve:3.x            3 hours ago            80/tcp, 192.168.x.x:8181->8080/tcp
        ↳ bind  /srv/services/kiwix → /data (ro)
        ↳ restart=unless-stopped  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

      ✔   node-exporter            prom/node-exporter:v1.x                  4 hours ago
        ↳ restart=unless-stopped  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

      ✔   paper                    itzg/minecraft-server:javaXX             2 days ago
        ↳ bind  /srv/services/paper → /data (rw)
        ↳ restart=unless-stopped  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

      ✔   prometheus               prom/prometheus:v3.x                     4 hours ago            192.168.x.x:9090->9090/tcp
        ↳ bind  /srv/config/prometheus → /etc/prometheus + /prometheus
        ↳ restart=unless-stopped  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

      ✔   traefik                  traefik:v3.x                             4 months ago           80/tcp
        ↳ bind  /srv/config/traefik → /traefik.yml + /dynamic
        ↳ restart=always  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

      ✔   uptime-kuma              louislam/uptime-kuma:1.x                 3 hours ago            3001/tcp
        ↳ bind  /srv/config/uptime-kuma → /app/data (rw)
        ↳ restart=unless-stopped  created=<SANITIZED_TIMESTAMP>  id=<CONTAINER_ID>

TASK [══════════════════════ MONITORING — PROMETHEUS TARGETS ═════════════] ****
ok: [homelab-node] =>
  msg: |2-
     Active targets: 4  |  Dropped: 0
     ✔  cadvisor            cadvisor:8080              interval=5s
     ✔  node                node-exporter:9100         interval=5s
     ✔  prometheus          prometheus:9090            interval=5s
     ✔  app-exporter        <sanitized-target>:PORT    interval=5s

TASK [══════════════════════ SERVICE ACCESS MAP ══════════════════════════] ****
ok: [homelab-node] =>
  msg: |2-
      SERVICE                  BIND:PORT                              BIND MOUNTS (config/data)               RESTART
      ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ✔ cadvisor                                                      host mounts                              unless-stopped
      ✔ cloudflared            127.0.0.1:8086->8086/tcp                                                       always
      ✔ filebrowser-public     10.x.x.x:8082->80/tcp                 config + cloud data                      unless-stopped
      ✔ filebrowser            192.168.x.x:8080->80/tcp              config + local data                      unless-stopped
      ✔ grafana                192.168.x.x:3000->3000/tcp            provisioning + data                      unless-stopped
      ✔ jellyfin-music         10.x.x.x:18096->8096/tcp              config + media                           unless-stopped
      ✔ jellyfin               192.168.x.x:8096->8096/tcp            config + media                           unless-stopped
      ✔ kiwix                  192.168.x.x:8181->8080/tcp            zim data                                 unless-stopped
      ✔ node-exporter                                                 host mounts                              unless-stopped
      ✔ paper                                                         server data                              unless-stopped
      ✔ prometheus             192.168.x.x:9090->9090/tcp            config + TSDB                            unless-stopped
      ✔ traefik                80/tcp                                static + dynamic config                  always
      ✔ uptime-kuma            3001/tcp                              app data                                 unless-stopped

      ── Open host ports (ss summary) ────────────────────────────────
      LISTEN 0      4096          192.168.x.x:3000       0.0.0.0:*
      LISTEN 0      4096          192.168.x.x:8096       0.0.0.0:*
      LISTEN 0      4096          192.168.x.x:8080       0.0.0.0:*
      LISTEN 0      4096          192.168.x.x:8181       0.0.0.0:*
      LISTEN 0      4096             127.0.0.1:8086      0.0.0.0:*
      LISTEN 0      4096          192.168.x.x:9090       0.0.0.0:*
      LISTEN 0      4096             10.x.x.x:8082       0.0.0.0:*
      LISTEN 0      4096            10.x.x.x:18096       0.0.0.0:*
      LISTEN 0      128                0.0.0.0:22        0.0.0.0:*
      LISTEN 0      4096      [::ffff:10.x.x.x]:25565          *:*
      LISTEN 0      128                   [::]:22           [::]:*

PLAY RECAP *********************************************************************
homelab-node               : ok=18   changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0

## Future Expansion

- K3s migration with Terraform provisioning
- Three-node architecture: control plane / public services / backup storage
- Off-host rsync backups + external USB HDD target
- CI/CD via GitHub Actions → Ansible
- GitOps via Forgejo or Gitea
