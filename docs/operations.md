# Operations

The operational pattern is deliberately repetitive. Each service gets a small
folder of playbooks with familiar actions, then the terminal control panel
discovers those actions and presents them as menus.

## Lifecycle Actions

Common actions include:

- deploy
- update
- backup
- restore
- backup-test
- status
- start
- stop
- restart
- remove
- R2 backup and restore for selected small-state services

## Operator Views

The main control panel gives a service inventory and health summary.

![Service inventory](assets/tresor-cli-dashboard.png)

Service-specific cockpits exist for radio/data lanes where plain playbook
output is not enough. Examples include plane watcher, satellite watcher, and
Tresor Index operations.

## Release Hosting

BatchYT update hosting is managed through a restricted VPS staging path. The
release process is designed around tag-driven builds, installer publication,
manifest promotion, and SHA256 checks before clients launch downloaded
installers.

## Monitoring

Prometheus collects host/container metrics and Grafana turns those into
operator dashboards. Tresor Index also exposes read-only dashboard data so RSS,
listing, and civic-ingest health can be checked without touching the database
directly.

![Grafana containers](assets/grafana-containers.png)

## Alerting And Capacity

The current private tree adds public-safe scaffolding for Grafana alerting:
provisioned Tresor infra rules, optional Discord relay delivery, and container
resource limits for Grafana, Prometheus, cAdvisor, node-exporter, Uptime Kuma,
Plane Watcher, and Tresor Index containers. Real webhook URLs, relay tokens,
mentions, and host-specific limits remain in private group vars or vaults.

The alert rules focus on operator-relevant failure modes:

- Prometheus scrape targets down.
- Managed containers missing or restart-storming.
- Host CPU, memory, and disk pressure.
- Containers running close to Docker memory or CPU caps.

## Civic Coverage Validation

Tresor Index now includes civic coverage commands for official Parliament vote
sources. The public code exposes the structure: scan official yearly totals,
store coverage totals, report missing coverage, and validate normalized vote
state before the public product relies on it.

## Recovery

Local backups are the first rollback path. Selected smaller service archives
can be copied to R2. Large media libraries, raw radio captures, and other bulk
state are intentionally excluded from public recovery docs.
