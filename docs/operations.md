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

## Recovery

Local backups are the first rollback path. Selected smaller service archives
can be copied to R2. Large media libraries, raw radio captures, and other bulk
state are intentionally excluded from public recovery docs.
