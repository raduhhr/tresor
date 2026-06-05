# Portfolio Evidence

This page mirrors the public-safe Tresor screenshots and project-card notes from
the DevOps portfolio site. The images are intentionally operator evidence:
control surfaces, runtime diagrams, dashboards, notification traces, and public
product views.

## Tresor Ops Platform

Tresor is the shared control plane for a home node, QA VM, Hetzner VPS edge,
monitoring, public status, recovery paths, update hosting, and small services.

![Tresor service inventory](assets/tresor-control-panel.png)

![Tresor topology](assets/tresor-ops-topology.png)

![Grafana action menu](assets/tresor-control-panel-grafana-actions.png)

![Infrastructure action menu](assets/tresor-control-panel-infrastructure-actions.png)

![Public status page](assets/status-page.png)

![Grafana containers dashboard](assets/grafana-containers.png)

![Grafana host dashboard](assets/grafana-host.png)

## Tresor Index

Tresor Index is the archive layer for sources that should not live as one-off
scripts. Disposable collectors write durable Postgres history: sources, fetch
runs, items, versions, observations, quarantine records, and civic vote tables.

![Tresor Index CLI](assets/tresor-index-cli.png)

![Tresor Index runtime map](assets/tresor-index-runtime-map.png)

![OLX listing digest](assets/notifications_olx.png)

![Grafana news overview](assets/grafana-news-overview.png)

![Grafana real-estate listings](assets/grafana-real-estate.png)

![Grafana Romanian news](assets/grafana-romanian-news.png)

![Grafana tech news](assets/grafana-tech-news.png)

## vot-parlament.ro Support

The civic product runs on the Tresor Index data layer. Official vote sources are
scheduled, normalized, versioned, and served into a public Astro app with source
links and visible coverage limits.

![vot-parlament.ro homepage](assets/vot_parlament_home.png)

![vot-parlament.ro bill page](assets/vot_parlament_proiect.png)

![vot-parlament.ro vote detail](assets/vot_parlament_vot.png)

![vot-parlament.ro politician profile](assets/vot_parlament_politician.png)

![vot-parlament.ro dark mode](assets/vot_parlament_darkmode.png)

![vot-parlament.ro Discord notification](assets/notifications_vot-parlament.png)

![Grafana parliament votes](assets/grafana-parliament-votes.png)

![Grafana API runtime](assets/grafana-index-runtime.png)

## Radio Watcher

The radio lane shares one RTL-SDR between ADS-B plane tracking and scheduled
weather-satellite capture. Satellite passes are predicted, captured, decoded,
and summarized through the same operational model as the rest of Tresor.

![Live planes map with weather overlay](assets/radio-planes-live-map.png)

![Plane watcher TUI](assets/radio-planes-tui.png)

![Meteor M2-4 corrected weather image](assets/radio-meteor-m2-4-corrected-map.png)

![Satellite orbit swath](assets/radio-satellite-orbit-swath.png)

![Antenna field setup](assets/radio-antenna-hill.jpeg)

![Satellite watcher TUI overview](assets/radio-satellite-tui.png)

![Satellite watcher capture controls](assets/radio-satellite-tui-bottom.png)

![Discord pass digest](assets/radio-discord-pass-digest.png)

## BatchYT Update Lane

BatchYT is a separate app, but its release/update lane is operated by Tresor: a
restricted VPS staging path, installer promotion, update manifest, and SHA256
client checks.

![BatchYT GUI](assets/batchyt-qt-gui-official.png)

![BatchYT release pipeline](assets/batchyt-release-pipeline-dark.svg)

![BatchYT TUI Docker profile](assets/batchyt-tui-docker.png)

![BatchYT installer and manifest proof](assets/batchyt-release-artifacts-proof.png)

## Portfolio Runtime

The portfolio site itself is also a Tresor-hosted surface: a static Astro build
served by nginx on the VPS edge, with Cloudflare in front and contact handling
isolated in a Worker path.

![Portfolio split homepage](assets/portfolio-home-split.png)

![Portfolio runtime overview](assets/portfolio-runtime-overview-dark.png)

![Portfolio contact and deploy path](assets/portfolio-contact-flow-dark.png)

## Utility Automations

Small Discord-facing services still get service users, timers, logs, secrets,
status playbooks, and recovery paths. The useful pattern is repeated: poll a
source, filter for relevant changes, dedupe, and post only when there is
something worth seeing.

![Notification channel list](assets/discord-notifications-list.png)

![Steam free-game notification](assets/discord-steam-free.png)

![RA watcher notification](assets/notifications_ra-watcher.png)

![Tech news notification](assets/notifications_tech-news.png)

![Minecraft join notification](assets/discord-mc-joins.png)

![Grafana Minecraft dashboard](assets/grafana-minecraft.png)
