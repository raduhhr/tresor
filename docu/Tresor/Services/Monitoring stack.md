# Monitoring Stack — Prometheus, Grafana, cAdvisor, Node Exporter

All components live **on the LAN only**, with no external exposure.  
Data flows one way — metrics are pulled internally; no pushes or WAN-bound telemetry.

```
[Node Exporter]     [cAdvisor]
       │                   │
       └─────> Prometheus ◄┘
                  │
                  ▼
               Grafana
```

&nbsp;

| Component | Role | Network | Access |
| --- | --- | --- | --- |
| **Prometheus** | Metrics collector | `internal_net` | `http://192.168.1.100:9090` |
| **Grafana** | Visualization dashboard | `internal_net` | `http://192.168.1.100:3000` |
| **Node Exporter** | Host metrics | host → internal_net | metrics pulled by Prometheus |
| **cAdvisor** | Docker metrics | container → internal_net | metrics pulled by Prometheus |
| **Uptime Kuma** | Public-facing uptime badge | `public_net` | CF Tunnel + Traefik via  <br>`mc-status.example.com` |

* * *

## Runtime Profile

| Setting | Value |
| --- | --- |
| **Deployment type** | Docker containers (managed by Ansible roles) |
| **Prometheus port** | 9090 (LAN-only) |
| **Grafana port** | 3000 (LAN-only) |
| **Exporter ports** | Node: 9100, cAdvisor: 8080 (Docker-internal only, no host port) |
| **Storage retention** | 15 days local (Prometheus volume) |
| **Data volume** | `/mnt/ssd/configs/prometheus` |
| **Dashboard data** | `/mnt/ssd/configs/grafana` |
| **Backup target** | `/mnt/data/backups/monitoring/` |

* * *

## Components & Roles

### `roles/prometheus`

- Deploys Prometheus container (`prom/prometheus:latest`)
    
- Networks: attaches **only** to `internal_net`
    
- Uses `/mnt/ssd/configs/prometheus/prometheus.yml` template
    
- Scrape targets defined dynamically:
    
    ```yaml
    scrape_configs:
      - job_name: "prometheus"
        static_configs:
          - targets: ["prometheus:9090"]
      - job_name: "node"
        static_configs:
          - targets: ["node-exporter:9100"]
      - job_name: "cadvisor"
        static_configs:
          - targets: ["cadvisor:8080"]
    ```
    
- Host port `9090` bound but **restricted to 192.168.0.0/24** via iptables.
    
- Integrates verify step to assert service health:
    
    - `/api/v1/status/runtimeinfo`
        
    - `/metrics` availability check
        

> **Gotcha:**  
> Docker’s internal DNS sometimes caches old container IPs.  
> If you redeploy exporters, run `docker network disconnect/connect internal_net <container>` to refresh DNS.

* * *

### `roles/grafana`

- Deploys Grafana (`grafana/grafana:latest`) on `internal_net`
    
- Environment:
    
    ```yaml
    GF_SECURITY_ADMIN_USER: admin
    GF_SECURITY_ADMIN_PASSWORD: "{{ vault_grafana_admin_pass }}"
    GF_SERVER_ROOT_URL: "http://192.168.1.100:3000"
    GF_INSTALL_PLUGINS: "grafana-piechart-panel"
    ```
    
- Auto-provisions datasource via template `datasource.yml.j2`:
    
    ```yaml
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        url: http://prometheus:9090
        access: proxy
        isDefault: true
    ```
    
- LAN-only; no Traefik routing.
    
- Config + dashboards persist under `/mnt/ssd/configs/grafana/`.
    

> **Gotcha:**  
> If dashboards appear empty after reboot, ensure `GF_PATHS_PROVISIONING` matches the bind path and the volume isn’t owned by root.  
> UID/GID 1000 required for persistent data.

* * *

### `cAdvisor`

- Containerized (`gcr.io/cadvisor/cadvisor:latest`)
    
- Exposes container-level CPU, memory, network metrics to Prometheus.
    
- Bound to internal_net; no external port mapping.
    
- Mounts `/var/run/docker.sock` read-only and `/` read-only.
    

> **Gotcha:**  
> Fails silently if `/var/lib/docker` not mounted read-only; verify volume mounts in role definition.

* * *

### `Node Exporter`

- Lightweight host metrics exporter (`prom/node-exporter:latest`)

- Runs on Tresor; exposes system metrics at `:9100` **on `internal_net` only — no host port published**.

- Prometheus scrapes it via Docker DNS (`node-exporter:9100`) over `internal_net`.

- Provides CPU load, RAM, disk I/O, network throughput, filesystem stats.
    

* * *

### `Uptime Kuma` *(mc public monitor)*

- Deployed on `public_net` behind Traefik + Cloudflared.
    
- URL: `https://mc-status.example.com`
    
- Monitors velocity only through simple pings.
    

* * *

## Security Model

- All metrics endpoints are **pull-only**, no pushes or auth bypass.
    
- No public exposure — Grafana and Prometheus bound to 192.168.0.0/24.
    
- `DOCKER-USER` chain enforces LAN-only for 9090 and 3000.
    
- Grafana admin password stored in vault.
    
- cAdvisor and Node Exporter don’t expose auth but are protected by LAN ACLs.
    

* * *

## Maintenance

| Task | Command |
| --- | --- |
| Restart all monitoring containers | `ansible-playbook playbooks/prometheus/deploy.yml` |
| View Prometheus status | `curl -s http://192.168.1.100:9090/-/healthy` |
| List Grafana dashboards | `docker exec -it grafana ls /var/lib/grafana/dashboards` |
| Cleanup old data | `docker exec prometheus rm -rf /prometheus/chunks_head` |
| Refresh dashboards | `ansible-playbook playbooks/grafana/deploy.yml --tags reload` |

* * *

## Gotchas

| Issue | Cause | Fix |
| --- | --- | --- |
| Prometheus UI loads slow | Large metrics history | Lower retention or prune old data |
| Grafana “Bad Gateway” | Restart order wrong | Ensure Prometheus is up first |
| Uptime Kuma false negatives | LAN DNS timing | Use IPs instead of hostnames in probes |
| CPU usage spike | cAdvisor sampling | Increase scrape interval to 30s |
| “permission denied” in Node Exporter | host protection | allow `/proc` read via `--path.procfs=/proc` |

* * *

## Notes

- Monitoring is **LAN-first** — nothing leaves the local network.
    
- cAdvisor + Node Exporter cover both Docker and host metrics, so no need for extra agents.
    
- Grafana dashboards are modular — you can later sync them to a `tresor-dashboards/` subfolder for version control.
    
- Entire stack can be redeployed safely; Prometheus + Grafana will auto-link via service discovery.
    

&nbsp;