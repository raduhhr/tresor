# Kiwix Ansible Role Documentation

## Available ZIM Archives Catalog

Before diving into the technical setup, here's a comprehensive list of ZIM archives you can add to your offline library. All can be downloaded from https://download.kiwix.org/zim/

### 🔥 Highly Recommended (Daily Use)

| Archive | Size | Update Frequency | Description | Download Path |
| --- | --- | --- | --- | --- |
| **Wikipedia (English)** | 111GB | Monthly | Complete English Wikipedia with images | `wikipedia/wikipedia_en_all_maxi_*.zim` |
| **Stack Overflow** | 90GB | Quarterly | All programming Q&A | `stack_exchange/stackoverflow.com_en_all_*.zim` |
| **Server Fault** | 8GB | Quarterly | Sysadmin/DevOps Q&A | `stack_exchange/serverfault.com_en_all_*.zim` |
| **iFixit** | 5GB | Monthly | Repair guides for electronics, appliances, vehicles | `other/ifixit_en_all_*.zim` |
| **Super User** | 10GB | Quarterly | General computing Q&A | `stack_exchange/superuser.com_en_all_*.zim` |

### 📚 Educational & Reference

| Archive | Size | Update Frequency | Description | Download Path |
| --- | --- | --- | --- | --- |
| **Khan Academy** | 30GB | Monthly | Complete curriculum (math, science, economics, history) | `khan-academy/khan-academy_en_all_*.zim` |
| **Project Gutenberg** | 70GB | Quarterly | 70,000+ classic books (public domain) | `gutenberg/gutenberg_en_all_*.zim` |
| **TED Talks** | 30GB | Monthly | All TED presentations with videos | `ted/ted_en_*.zim` |
| **Wiktionary (English)** | 10GB | Monthly | Comprehensive dictionary with etymology | `wiktionary/wiktionary_en_all_*.zim` |
| **Wikiversity** | 3GB | Monthly | Educational resources and learning materials | `wikiversity/wikiversity_en_all_*.zim` |
| **Wikibooks** | 5GB | Monthly | Free textbooks and educational books | `wikibooks/wikibooks_en_all_*.zim` |

### 🗺️ Travel & Geography

| Archive | Size | Update Frequency | Description | Download Path |
| --- | --- | --- | --- | --- |
| **Wikivoyage** | 1GB | Monthly | Travel guides for every destination | `wikivoyage/wikivoyage_en_all_*.zim` |
| **OpenStreetMap (World)** | 50GB | Monthly | Basic world map (no routing) | `openstreetmap/openstreetmap_world_*.zim` |
| **OpenStreetMap (Europe)** | 8GB | Monthly | European maps | `openstreetmap/openstreetmap_europe_*.zim` |
| **OpenStreetMap (North America)** | 10GB | Monthly | North American maps | `openstreetmap/openstreetmap_north-america_*.zim` |

### 🔬 Scientific & Academic

| Archive | Size | Update Frequency | Description | Download Path |
| --- | --- | --- | --- | --- |
| **arXiv** | 300GB | Monthly | Physics, math, CS research papers | `arxiv/arxiv_*.zim` |
| **PhET Simulations** | 2GB | Quarterly | Interactive science/math simulations | `phet/phet_en_*.zim` |
| **StackExchange: Physics** | 5GB | Quarterly | Physics Q&A | `stack_exchange/physics.stackexchange.com_en_all_*.zim` |
| **StackExchange: Mathematics** | 15GB | Quarterly | Math Q&A | `stack_exchange/math.stackexchange.com_en_all_*.zim` |

### 🏥 Medical & Health

| Archive | Size | Update Frequency | Description | Download Path |
| --- | --- | --- | --- | --- |
| **WikiDoc** | 15GB | Quarterly | Medical encyclopedia | `wikimed/wikidoc_en_all_*.zim` |
| **Radiopaedia** | 100GB | Quarterly | Radiology cases and imaging | `other/radiopaedia_en_all_*.zim` |
| **Practical Action** | 1GB | Annually | Sustainable development resources | `other/practicalaction_en_all_*.zim` |

### 💻 All Stack Exchange Sites (~200GB total)

Every Stack Exchange community is available as a ZIM. Some notable ones:

- **Ask Ubuntu** (5GB) - Ubuntu-specific Q&A
- **Unix & Linux** (8GB) - Linux/Unix systems
- **Database Administrators** (5GB) - SQL, database design
- **Information Security** (3GB) - Cybersecurity
- **Network Engineering** (2GB) - Networking
- **Raspberry Pi** (1GB) - Pi-specific Q&A
- **Software Engineering** (3GB) - Software design/architecture
- **Code Review** (5GB) - Code review and best practices
- **DevOps** (1GB) - DevOps practices
- **Ask Different** (5GB) - Apple/macOS Q&A

Full list: https://download.kiwix.org/zim/stack_exchange/

### 🌍 Wikipedia in Other Languages

| Language | Size | Download Path |
| --- | --- | --- |
| **German** | 60GB | `wikipedia/wikipedia_de_all_maxi_*.zim` |
| **French** | 40GB | `wikipedia/wikipedia_fr_all_maxi_*.zim` |
| **Spanish** | 35GB | `wikipedia/wikipedia_es_all_maxi_*.zim` |
| **Russian** | 30GB | `wikipedia/wikipedia_ru_all_maxi_*.zim` |
| **Italian** | 25GB | `wikipedia/wikipedia_it_all_maxi_*.zim` |
| **Portuguese** | 20GB | `wikipedia/wikipedia_pt_all_maxi_*.zim` |
| **Your language** | varies | `wikipedia/wikipedia_<lang>_all_maxi_*.zim` |
| **Polish** | 15GB | `wikipedia/wikipedia_pl_all_maxi_*.zim` |
| **Dutch** | 15GB | `wikipedia/wikipedia_nl_all_maxi_*.zim` |
| **Arabic** | 10GB | `wikipedia/wikipedia_ar_all_maxi_*.zim` |

### 📦 Specialized Collections

| Archive | Size | Description | Download Path |
| --- | --- | --- | --- |
| **MDN Web Docs** | 2GB | Web development documentation | `other/mdn_en_all_*.zim` |
| **Arch Wiki** | 1GB | Arch Linux documentation | `other/archwiki_en_all_*.zim` |
| **How Stuff Works** | 3GB | Explanations of how things work | `other/howstuffworks_en_all_*.zim` |
| **Internet Archive** | Varies | Select collections from archive.org | `other/` (various) |
| **Hacker News** | 5GB | Archive of HN posts/comments | `other/hackernews_*.zim` |

### 💾 Storage Recommendations by Use Case

**Developer/Homelab (330GB):**

- Wikipedia EN (111GB)
- Stack Overflow (90GB)
- Server Fault (8GB)
- Super User (10GB)
- iFixit (5GB)
- Arch Wiki (1GB)
- MDN (2GB)
- Wikivoyage (1GB)

**Student/Learner (250GB):**

- Wikipedia EN (111GB)
- Khan Academy (30GB)
- Project Gutenberg (70GB)
- TED Talks (30GB)
- Wiktionary (10GB)
- PhET Simulations (2GB)

**Researcher/Academic (550GB):**

- Wikipedia EN (111GB)
- arXiv (300GB)
- All relevant Stack Exchange sites (50GB)
- WikiDoc (15GB)
- Wiktionary (10GB)
- Wikibooks (5GB)

**Everything Essential (~1TB):** All highly recommended + educational + major Stack Exchange sites

* * *

## Overview

This Ansible role deploys Kiwix-serve on tresor to provide offline access to ZIM archives (Wikipedia, Stack Overflow, and other knowledge bases) over your local network.

**What it does:**

- Manages ZIM file transfers from control machine to tresor SSD
- Configures firewall rules (iptables) for LAN access
- Deploys and manages Kiwix Docker container
- Serves multiple ZIM archives from a single container
- Resource-limited to prevent system impact

## Architecture

```
Legion (Control Machine)
    ↓ [Optional: rsync transfer]
Tresor (/mnt/ssd/services/kiwix/)
    ├── wikipedia_en_all_maxi_2025-08.zim
    ├── stack_overflow_en_all.zim
    └── [any other .zim files]
    ↓ [Docker volume mount]
Kiwix Container
    ↓ [Port 8181]
LAN Devices (192.168.0.0/24)
```

## Requirements

### Control Machine (legion)

- Ansible 2.9+
- Collections:
    - `ansible.posix`
    - `community.general`
    - `community.docker`

### Target Host (tresor)

- Docker installed and running
- rsync (installed by role if missing)
- Docker networks: `internal_net`, `lan_pub`
- SSD mounted at `/mnt/ssd/`
- iptables for firewall management

### Network

- LAN subnet: `192.168.0.0/24` (configurable)
- Available port: `8181` (configurable)

## Role Variables

### defaults/main.yml

```yaml
# Source ZIM path (on Ansible control machine = legion)
kiwix_zim_src_path: "/mnt/samsung/PROJECTS/kiwix/wikipedia_en_all_maxi_2025-08.zim"

# Destination path (on tresor SSD)
kiwix_zim_dest_dir: "/mnt/ssd/services/kiwix"
kiwix_zim_dest_path: "{{ kiwix_zim_dest_dir }}/{{ kiwix_zim_src_path | basename }}"

# Container configuration
kiwix_container_name: "kiwix"
kiwix_image: "ghcr.io/kiwix/kiwix-serve:latest"

# Network exposure
kiwix_bind_addr: "192.168.1.100"    # LAN interface only
kiwix_host_port: 8181              # External port on tresor
kiwix_container_port: 8080         # Internal container port

# Container ownership (must match non-root user inside kiwix-serve image)
kiwix_uid: 1000
kiwix_gid: 1000

# Docker networks
kiwix_networks:
  - "internal_net"
  - "lan_pub"

# Firewall
kiwix_allow_from_cidr: "192.168.0.0/24"

# File transfer behavior
kiwix_sync_enabled: true           # Enable/disable rsync transfer
kiwix_sync_partial: true           # Enable partial/resumable transfers
```

### Production Variables (group_vars or playbook)

```yaml
---
# Minimal production override
kiwix_host_port: 8181
kiwix_allow_from_cidr: "192.168.0.0/24"
kiwix_sync_enabled: false  # Skip if manually transferring files
```

## Usage

### Basic Deployment

```yaml
# playbooks/kiwix/deploy.yml
- name: Deploy Kiwix Wikipedia (LAN)
  hosts: tresor
  vars:
    kiwix_sync_enabled: false  # Skip rsync if file already on tresor
  roles:
    - kiwix
```

Run the playbook:

```bash
ansible-playbook -i inventory/hosts.ini playbooks/kiwix/deploy.yml
```

### First-Time Setup with File Transfer

If you want Ansible to transfer the ZIM file:

```bash
# Ensure source file exists on legion
ls -lh /mnt/samsung/PROJECTS/kiwix/wikipedia_en_all_maxi_2025-08.zim

# Run with sync enabled
ansible-playbook -i inventory/hosts.ini playbooks/kiwix/deploy.yml \
  -e "kiwix_sync_enabled=true"
```

### Manual File Transfer (Recommended for Large Files)

For 100GB+ files, manual transfer via Filebrowser or rsync is often more reliable:

```bash
# Option 1: Via Filebrowser
# Upload to tresor, then move to destination
ssh tresor
sudo mv /path/to/uploaded/file.zim /mnt/ssd/services/kiwix/
sudo chmod 644 /mnt/ssd/services/kiwix/*.zim

# Option 2: Direct rsync from legion
rsync -ah --progress \
  /mnt/samsung/PROJECTS/kiwix/wikipedia_en_all_maxi_2025-08.zim \
  ansible@homelab:/mnt/ssd/services/kiwix/

# Then deploy with sync disabled
ansible-playbook -i inventory/hosts.ini playbooks/kiwix/deploy.yml \
  -e "kiwix_sync_enabled=false"
```

## Adding Multiple ZIM Archives

**CRITICAL: Kiwix-serve does NOT auto-scan directories.** You must explicitly list each ZIM file in the command. The container will NOT automatically detect new files you drop into the folder.

### How Kiwix-serve Works with Multiple ZIMs

The Docker image's entrypoint (`/usr/local/bin/start.sh`) expects:

- File paths as arguments (e.g., `/data/file1.zim /data/file2.zim`)
- It automatically adds `--port=8080` internally
- **Do NOT pass --port yourself** - it will duplicate and cause errors

### Step 1: Download Additional ZIMs

Popular sources:

- **Official Library:** https://library.kiwix.org/
- **Direct Downloads:** https://download.kiwix.org/zim/

Example downloads:

```bash
# Stack Overflow (~90GB)
wget https://download.kiwix.org/zim/stack_exchange/stackoverflow.com_en_all_2025-01.zim

# Server Fault (~8GB) - for sysadmin/devops
wget https://download.kiwix.org/zim/stack_exchange/serverfault.com_en_all_2025-01.zim

# iFixit repair guides (~5GB)
wget https://download.kiwix.org/zim/other/ifixit_en_all_2025-01.zim

# Your language Wikipedia
wget https://download.kiwix.org/zim/wikipedia/wikipedia_<lang>_all_maxi_<date>.zim
```

### Step 2: Transfer to Tresor

```bash
# Upload to kiwix directory
scp *.zim ansible@homelab:/tmp/
ssh tresor
sudo mv /tmp/*.zim /mnt/ssd/services/kiwix/
sudo chmod 644 /mnt/ssd/services/kiwix/*.zim
```

### Step 3: Update Ansible Role Command

**You must manually update the container command** to include the new ZIM file.

Edit `roles/kiwix/tasks/main.yml` and update the command section:

```yaml
- name: Run Kiwix container serving the ZIM
  community.docker.docker_container:
    name: "{{ kiwix_container_name }}"
    image: "{{ kiwix_image }}"
    pull: true
    restart_policy: unless-stopped
    command:
      - "/data/wikipedia_en_all_maxi_2025-08.zim"
      - "/data/stackoverflow.com_en_all_2025-01.zim"  # Add new file
      - "/data/ifixit_en_all_2025-01.zim"             # Add another
    ports:
      - "{{ kiwix_bind_addr }}:{{ kiwix_host_port }}:{{ kiwix_container_port }}"
    volumes:
      - "{{ kiwix_zim_dest_dir }}:/data:ro"
    networks:
      - name: internal_net
      - name: lan_pub
    memory: "2g"
    cpus: 1.0
    cpu_shares: 512
  become: true
```

**IMPORTANT:**

- Each ZIM file must be on its own line with full `/data/filename.zim` path
- Do NOT include `--port` - the entrypoint adds it automatically
- `community.docker.docker_container` automatically detects command changes and recreates the container — just redeploy

### Step 4: Redeploy

```bash
ansible-playbook -i inventory/hosts.ini playbooks/kiwix/deploy.yml \
  -e "kiwix_sync_enabled=false"
```

All ZIM files will now appear as separate books in the Kiwix interface.

## Resource Limits

The container is configured with the following limits:

```yaml
memory: "2g"          # Hard limit: 2GB RAM
cpus: 1.0             # Maximum 1 CPU core
cpu_shares: 512       # Half priority if CPU contested
```

These limits are appropriate for:

- Single user browsing
- Multiple open tabs (20+)
- Serving 100GB+ ZIM files
- Multiple ZIM archives simultaneously

Typical resource usage:

- **Idle:** 200-300MB RAM, <1% CPU
- **Active browsing:** 400-800MB RAM, 5-15% CPU per page load
- **Multiple tabs:** 800MB-1.5GB RAM

## Accessing Kiwix

### From LAN Devices

**Web Interface:**

- URL: `http://tresor:8181` or `http://192.168.1.100:8181`
- Works on: Desktop, laptop, phone, tablet (any device on LAN)

**How to use:**

1.  Open URL in web browser
2.  Click on a "book" (ZIM archive) to open it
3.  Use search box to find articles
4.  Browse categories, random articles, etc.

### From Tresor (Local)

```bash
curl http://127.0.0.1:8181
```

## Firewall Configuration

The role automatically configures iptables rules:

```bash
# Rule added by role
iptables -A INPUT -p tcp --dport 8181 -s 192.168.0.0/24 -j ACCEPT -m comment --comment "Kiwix (LAN)"

# Rules are persisted to
/etc/iptables/rules.v4
```

To verify:

```bash
ansible tresor -i inventory/hosts.ini -m shell \
  -a "iptables -L INPUT -n | grep 8181" --become
```

## Troubleshooting

### Container Crash Loop (Restarting)

**Symptom:**

```bash
docker ps -a | grep kiwix
# Shows: Restarting (1) X seconds ago
```

**Check logs:**

```bash
docker logs kiwix --tail 50
```

**Common causes:**

1.  **Permission denied on ZIM files**
    
    ```
    Unable to add the ZIM file '/data/...' to the internal library.
    ```
    
    **Fix:**
    
    ```bash
    sudo chmod 644 /mnt/ssd/services/kiwix/*.zim
    docker restart kiwix
    ```
    
2.  **Wrong command path - trying to scan directory**
    
    ```
    Unable to add the ZIM file '/data' to the internal library.
    ```
    
    **Cause:** Kiwix-serve does NOT auto-scan directories. You tried `/data` or `/data/` instead of explicit file paths.
    
    **Fix:** Update command to list specific files:
    
    ```yaml
    command:
      - "/data/wikipedia_en_all_maxi_2025-08.zim"
      # NOT: "/data" or "/data/"
    ```
    
3.  **Duplicate --port argument**
    
    ```
    Unexpected argument: --port=8080, --port=8080, /data/...
    ```
    
    **Cause:** The Docker image's entrypoint already adds `--port=8080`. Adding it in the command duplicates it.
    
    **Fix:** Remove `--port` from command entirely:
    
    ```yaml
    command:
      - "/data/wikipedia_en_all_maxi_2025-08.zim"  # NO --port here
    ```
    
4.  **Help text in logs** If logs show the kiwix-serve help/usage text, the command arguments are malformed.
    
    **Correct format:**
    
    ```yaml
    command:
      - "/data/file1.zim"
      - "/data/file2.zim"
    ```
    
    **Incorrect formats:**
    
    ```yaml
    command: "/data"              # Wrong: tries to read /data as file
    command: "/data/"             # Wrong: trailing slash
    command: ["--port=8080", ...] # Wrong: duplicate port
    ```
    
5.  **Missing file**
    
    ```bash
    ls -lh /mnt/ssd/services/kiwix/
    # Verify ZIM files exist
    ```
    

### Container Not Recreating After Command Change

**Symptom:** You updated the Ansible role but container still uses old command.

**Cause:** This should not happen — `community.docker.docker_container` compares the full container spec (including `command`) against the running container and will recreate automatically when a difference is detected.

**Fix:** Just redeploy:

```bash
ansible-playbook -i inventory/hosts.ini playbooks/kiwix/deploy.yml
```

If the container is somehow stuck, force it manually:

```bash
ssh tresor
sudo docker stop kiwix && sudo docker rm kiwix
exit
ansible-playbook -i inventory/hosts.ini playbooks/kiwix/deploy.yml
```

### Smoke Test Failing

**Symptom:** Playbook hangs at "Smoke test from tresor host" task

**Check container status:**

```bash
docker ps | grep kiwix
# Should show "Up X seconds"
```

**If container is up but smoke test fails:**

```bash
# Test manually
curl -I http://127.0.0.1:8181

# Check if port is listening
ss -tlnp | grep 8181
```

**Common causes:**

- Container still starting up (first start can take 30-60s for large ZIMs)
- Port conflict (another service on 8181)
- Firewall blocking localhost (rare)

### No Content in Web Interface

**Symptom:** Web interface loads but shows "No result" when searching

**This is expected behavior:**

1.  You must **click on a "book"** (ZIM file) first to open it
2.  Only then can you search within that ZIM

**To verify ZIMs are loaded:**

```bash
curl http://192.168.1.100:8181/catalog/v2/entries
# Should return JSON with available ZIM files
```

### Performance Issues

**Slow page loads:**

- Check disk I/O: `iostat -x 2`
- Verify SSD is being used: `df -h /mnt/ssd`
- Check container stats: `docker stats kiwix --no-stream`

**High memory usage:**

- Increase memory limit if needed
- Current limit: 2GB (configurable in role)
- Container will be killed if exceeding limit

### File Transfer Issues

**rsync fails with "cannot be used with --delay-updates"**

- This is a known issue with `ansible.posix.synchronize` and `--append-verify`
- **Solution:** Use manual transfer methods (Filebrowser, direct rsync)
- Or disable sync: `kiwix_sync_enabled: false`

**Slow transfer speeds:**

- Expected: 30-70 MB/s depending on source/destination disk speeds
- HDD reads: typically 30-50 MB/s
- SSD writes: 200+ MB/s (limited by HDD read speed)
- Network: Up to 70 MB/s on gigabit LAN

## Maintenance

### Updating ZIM Files

Wikipedia releases new dumps monthly. To update:

```bash
# 1. Download new ZIM to legion
wget https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_maxi_2025-09.zim

# 2. Transfer to tresor (manually or via role)

# 3. Remove old ZIM
ssh tresor
sudo rm /mnt/ssd/services/kiwix/wikipedia_en_all_maxi_2025-08.zim

# 4. Restart container
docker restart kiwix
```

### Container Updates

```bash
# Pull latest image and recreate container
ansible-playbook -i inventory/hosts.ini playbooks/kiwix/deploy.yml
```

The role automatically pulls the latest image on each run.

### Checking Status

```bash
# Container status
ansible tresor -i inventory/hosts.ini -m shell \
  -a "docker ps | grep kiwix" --become

# Resource usage
ansible tresor -i inventory/hosts.ini -m shell \
  -a "docker stats kiwix --no-stream" --become

# Disk space
ansible tresor -i inventory/hosts.ini -m shell \
  -a "df -h /mnt/ssd/services/kiwix" --become

# Logs
ansible tresor -i inventory/hosts.ini -m shell \
  -a "docker logs kiwix --tail 20" --become
```

### Alternative: Variable-Based ZIM Management

For easier management of multiple ZIMs, you can use variables instead of hardcoding file paths.

**In `defaults/main.yml`:**

```yaml
# List of ZIM files to serve
kiwix_zim_files:
  - "wikipedia_en_all_maxi_2025-08.zim"
  - "stackoverflow.com_en_all_2025-01.zim"
  - "ifixit_en_all_2025-01.zim"
```

**In `tasks/main.yml` container task:**

```yaml
command: "{{ kiwix_zim_files | map('regex_replace', '^', '/data/') | list }}"
```

This converts the list to `["/data/file1.zim", "/data/file2.zim", ...]`

**To add a new ZIM:**

1.  Transfer file to tresor
2.  Add filename to `kiwix_zim_files` list
3.  Redeploy

**Benefits:**

- Centralized file list
- Easier to enable/disable ZIMs (comment out lines)
- Can override in group_vars or playbook vars

**Example with overrides:**

```yaml
# playbooks/kiwix/deploy.yml
- name: Deploy Kiwix Wikipedia (LAN)
  hosts: tresor
  vars:
    kiwix_sync_enabled: false
    kiwix_zim_files:
      - "wikipedia_en_all_maxi_2025-08.zim"
      - "stackoverflow.com_en_all_2025-01.zim"
  roles:
    - kiwix
```

## Advanced Configuration

### Changing Ports

Update variables:

```yaml
kiwix_host_port: 8282  # New external port
```

Re-run playbook. Old iptables rules will remain (manual cleanup required).

### Adding to Different Networks

Update networks list:

```yaml
kiwix_networks:
  - "my_network_1"
  - "my_network_2"
```

Ensure networks exist:

```bash
docker network ls
```

### Adjusting Resource Limits

For multiple concurrent users or very large ZIM collections:

```yaml
# In playbook or group_vars
kiwix_container_memory: "4g"
kiwix_container_cpus: 2.0
```

Update the container task in `tasks/main.yml`:

```yaml
memory: "{{ kiwix_container_memory | default('2g') }}"
cpus: "{{ kiwix_container_cpus | default(1.0) }}"
```

### Serving Specific ZIMs Only

Kiwix-serve **ALWAYS** requires explicit file paths - it never auto-scans. The command format is:

**Single ZIM:**

```yaml
command:
  - "/data/wikipedia_en_all_maxi_2025-08.zim"
```

**Multiple ZIMs:**

```yaml
command:
  - "/data/wikipedia_en_all_maxi_2025-08.zim"
  - "/data/stackoverflow.com_en_all_2025-01.zim"
  - "/data/ifixit_en_all_2025-01.zim"
```

**What DOESN'T work:**

```yaml
# ❌ Directory paths don't work
command: ["/data"]
command: ["/data/"]

# ❌ Wildcards don't work
command: ["/data/*.zim"]

# ❌ Don't add --port (entrypoint handles it)
command: ["--port=8080", "/data/file.zim"]
```

Each ZIM file you want to serve must be explicitly listed in the command array.

## Security Considerations

### Network Exposure

- **Default:** Only accessible from LAN (192.168.0.0/24)
- **No authentication:** Anyone on LAN can access
- **Read-only mount:** Container cannot modify ZIM files
- **Non-root container:** Kiwix-serve runs as non-privileged user

### Firewall Rules

The role adds specific iptables rules. To restrict further:

```yaml
# Allow only specific IPs
kiwix_allow_from_cidr: "192.168.0.100"  # Single IP

# Or specific subnet
kiwix_allow_from_cidr: "192.168.0.0/28"  # Only .0-.15
```

### Data Privacy

ZIM archives contain public knowledge bases. However:

- User queries are logged in container logs
- No external analytics or tracking
- Fully offline after deployment

## Performance Tuning

### SSD vs HDD

**Current setup:** ZIMs on SSD (`/mnt/ssd/services/kiwix/`)

Benefits:

- Fast random access for article lookups
- Quick search indexing
- Minimal latency

**If using HDD:**

- Expect 3-5x slower page loads
- Search will be noticeably slower
- Consider moving only frequently-used ZIMs to SSD

### Caching

Kiwix-serve caches articles in memory. With 2GB limit:

- Can cache 50-100+ articles
- Frequently accessed content stays cached
- First visit to article: slower (disk read)
- Subsequent visits: fast (memory cache)

## Common ZIM Archives

### Recommended Collection (Total: ~330GB)

| ZIM Archive | Size | Update Frequency | Usefulness |
| --- | --- | --- | --- |
| Wikipedia EN | 111GB | Monthly | ⭐⭐⭐⭐⭐ Daily use |
| Stack Overflow | 90GB | Quarterly | ⭐⭐⭐⭐⭐ Coding/troubleshooting |
| Server Fault | 8GB | Quarterly | ⭐⭐⭐⭐ Sysadmin/DevOps |
| iFixit | 5GB | Monthly | ⭐⭐⭐⭐ Repairs/troubleshooting |
| Wikivoyage | 1GB | Monthly | ⭐⭐⭐ Travel reference |

### Nice-to-Have (Additional ~400GB)

| ZIM Archive | Size | Update Frequency | Usefulness |
| --- | --- | --- | --- |
| Project Gutenberg | 70GB | Quarterly | ⭐⭐ Books (if you read classics) |
| Khan Academy | 30GB | Monthly | ⭐⭐⭐ Learning/education |
| TED Talks | 30GB | Monthly | ⭐⭐ Educational videos |
| Wiktionary | 10GB | Monthly | ⭐⭐ Dictionary/etymology |
| OpenStreetMap (region) | 5-50GB | Monthly | ⭐⭐⭐ Maps (basic, no routing) |

### Specialized Archives

- **arXiv** (~300GB) - Research papers (physics, math, CS)
- **WikiDoc** (~15GB) - Medical encyclopedia
- **Radiopaedia** (~100GB) - Medical imaging cases
- **All Stack Exchange** (~200GB) - Every SE site

## Example: Complete Setup

```bash
# 1. Download ZIMs on legion
cd /mnt/samsung/PROJECTS/kiwix/
wget https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_maxi_2025-08.zim
wget https://download.kiwix.org/zim/stack_exchange/stackoverflow.com_en_all_2025-01.zim
wget https://download.kiwix.org/zim/other/ifixit_en_all_2025-01.zim

# 2. Transfer to tresor (via Filebrowser or rsync)
rsync -ah --progress *.zim ansible@homelab:/tmp/
ssh tresor
sudo mv /tmp/*.zim /mnt/ssd/services/kiwix/
sudo chown ansible:ansible /mnt/ssd/services/kiwix/*.zim
sudo chmod 644 /mnt/ssd/services/kiwix/*.zim
exit

# 3. Update roles/kiwix/tasks/main.yml
# Add the new files to the command:
# command:
#   - "/data/wikipedia_en_all_maxi_2025-08.zim"
#   - "/data/stackoverflow.com_en_all_2025-01.zim"
#   - "/data/ifixit_en_all_2025-01.zim"

# 4. Deploy with Ansible
cd ~/Desktop/tresor/ansible
ansible-playbook -i inventory/hosts.ini playbooks/kiwix/deploy.yml \
  -e "kiwix_sync_enabled=false"

# 5. Verify
curl http://192.168.1.100:8181/catalog/v2/entries | jq

# 6. Access from browser
# Open: http://tresor:8181
# You'll see 3 books: Wikipedia, Stack Overflow, iFixit
```

## Key Lessons Learned

### Docker Image Behavior

1.  **The entrypoint adds --port automatically**
    
    - Image uses `/usr/local/bin/start.sh` as entrypoint
    - This script automatically adds `--port=8080`
    - Adding it in the command causes "duplicate argument" errors
    - **Solution:** Only pass ZIM file paths in command
2.  **Kiwix-serve does NOT auto-scan directories**
    
    - Passing `/data` or `/data/` tries to read it as a single file
    - It does NOT discover ZIM files in that directory
    - **You must explicitly list each ZIM file** in the command
    - This is by design - kiwix-serve wants explicit control over what's served
3.  **Ansible DOES auto-detect command changes**

    - `community.docker.docker_container` compares the full container spec against the running container
    - Changing `command:` in the role will trigger recreation automatically on the next deploy
    - No `recreate: true` needed — just redeploy
    - If a container is genuinely stuck, `docker stop/rm` then redeploy as a last resort

### File Management

4.  **Permissions matter**
    
    - Container runs as non-root user `user`
    - ZIM files need `644` permissions (world-readable)
    - Directory needs `755` permissions
    - Without this, container crashes with "Unable to add ZIM file" errors
5.  **Large file transfers**
    
    - rsync's `--append-verify` conflicts with `--delay-updates` (from `archive: true`)
    - For 100GB+ files, manual transfer (Filebrowser, direct rsync) is more reliable
    - Use `kiwix_sync_enabled: false` and transfer manually

### Troubleshooting Approach

6.  **Check logs first, always**
    
    - `docker logs kiwix --tail 50` tells you exactly what's wrong
    - Help text in logs = malformed command
    - "Unable to add" = permissions or wrong path
    - "Unexpected argument" = duplicate --port
7.  **Test manually before Ansible**
    
    - Run `docker run` manually to verify correct syntax
    - Once manual command works, replicate in Ansible
    - Saves time debugging Ansible vs Docker issues

## References

- **Kiwix Official:** https://www.kiwix.org/
- **ZIM Library:** https://library.kiwix.org/
- **ZIM Downloads:** https://download.kiwix.org/zim/
- **Kiwix-serve Docker:** https://github.com/kiwix/kiwix-tools
- **ZIM Format Spec:** https://wiki.openzim.org/wiki/ZIM_file_format

## License

This role is provided as-is for personal/homelab use.

## Support

For issues:

1.  Check troubleshooting section above
2.  Review container logs: `docker logs kiwix`
3.  Verify file permissions and paths
4.  Check Kiwix community forums

* * *

**Last Updated:** February 9, 2026  
**Author:** admin (tresor homelab)  
**Version:** 2.0

**Note:** This documentation reflects real-world troubleshooting and lessons learned during deployment. The kiwix-serve Docker image's behavior with entrypoints and command arguments was not immediately obvious from documentation, requiring extensive debugging to determine the correct configuration. All troubleshooting scenarios listed here were actually encountered and resolved during the initial deployment.

**Time Investment:** ~3 hours of troubleshooting container crashes, permission issues, and command format problems. Worth it for 111GB of offline knowledge. 🚀📚