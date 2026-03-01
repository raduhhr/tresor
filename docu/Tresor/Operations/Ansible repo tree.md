# Ansible repo tree

```
admin@legion:~/Desktop/tresor/ansible$ tree
.
├── ansible.cfg
├── ansible_dump.txt
├── requirements.yml
├── tresor-cli.py
├── inventory
│   ├── hosts.ini
│   ├── host_vars
│   │   └── tresor-vps.yml
│   └── group_vars
│       ├── all
│       │   └── main.yml
│       ├── prod
│       │   ├── bday-notifier.yml
│       │   ├── filebrowser-public.yml
│       │   ├── filebrowser.yml
│       │   ├── grafana.yml
│       │   ├── kiwix.yml
│       │   ├── main.yml
│       │   ├── mc.yml
│       │   ├── prometheus.yml
│       │   ├── vault.yml
│       │   └── versions.yml
│       ├── qa
│       │   ├── main.yml
│       │   ├── mc.yml
│       │   └── vault.yml
│       ├── tresor
│       │   └── network.yml
│       └── vps
│           ├── main.yml
│           └── vault.yml
├── vaults
│   ├── prod.vault
│   ├── qa.vault
│   └── vps.vault
├── playbooks
│   ├── bday-notifier
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restore.yml
│   │   └── status.yml
│   ├── cloudflared
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restart.yml
│   │   ├── restore.yml
│   │   ├── start.yml
│   │   ├── status.yml
│   │   ├── stop.yml
│   │   └── update.yml
│   ├── content-notifier
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── reset-state.yml
│   │   └── restore.yml
│   ├── filebrowser
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restart.yml
│   │   ├── restore.yml
│   │   ├── start.yml
│   │   ├── status.yml
│   │   ├── stop.yml
│   │   └── update.yml
│   ├── filebrowser-public
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restart.yml
│   │   ├── restore.yml
│   │   ├── start.yml
│   │   ├── status.yml
│   │   ├── stop.yml
│   │   └── update.yml
│   ├── grafana
│   │   ├── backup-test.yml
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restart.yml
│   │   ├── restore.yml
│   │   ├── start.yml
│   │   ├── status.yml
│   │   ├── stop.yml
│   │   └── update.yml
│   ├── infra
│   │   ├── backup-all.yml
│   │   ├── deploy-wireguard.yml
│   │   ├── firewall.yml
│   │   ├── setup-base.yml
│   │   ├── setup-docker.yml
│   │   ├── setup-networks.yml
│   │   ├── setup-wireguard-key.yml
│   │   ├── status-all.yml
│   │   ├── verify-base.yml
│   │   ├── verify-docker.yml
│   │   ├── verify-networks.yml
│   │   └── verify-wireguard.yml
│   ├── jellyfin
│   │   ├── backup-test.yml
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restart.yml
│   │   ├── restore.yml
│   │   ├── start.yml
│   │   ├── status.yml
│   │   ├── stop.yml
│   │   └── update.yml
│   ├── jellyfin-music
│   │   ├── backup-test.yml
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restart.yml
│   │   ├── restore.yml
│   │   ├── start.yml
│   │   ├── status.yml
│   │   ├── stop.yml
│   │   └── update.yml
│   ├── kiwix
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restart.yml
│   │   ├── restore.yml
│   │   ├── start.yml
│   │   ├── status.yml
│   │   ├── stop.yml
│   │   └── update.yml
│   ├── motd
│   │   └── deploy.yml
│   ├── paper
│   │   ├── backup-test.yml
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restart.yml
│   │   ├── restore.yml
│   │   ├── start.yml
│   │   ├── status.yml
│   │   ├── stop.yml
│   │   └── update.yml
│   ├── prometheus
│   │   ├── backup-test.yml
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restart.yml
│   │   ├── restore.yml
│   │   ├── start.yml
│   │   ├── status.yml
│   │   ├── stop.yml
│   │   └── update.yml
│   ├── steam-free-notifier
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restore.yml
│   │   └── status.yml
│   ├── traefik
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restart.yml
│   │   ├── restore.yml
│   │   ├── start.yml
│   │   ├── status.yml
│   │   ├── stop.yml
│   │   └── update.yml
│   ├── uptime-kuma
│   │   ├── backup-test.yml
│   │   ├── backup.yml
│   │   ├── deploy.yml
│   │   ├── remove.yml
│   │   ├── restart.yml
│   │   ├── restore.yml
│   │   ├── start.yml
│   │   ├── status.yml
│   │   ├── stop.yml
│   │   ├── update.yml
│   │   └── verify.yml
│   └── vps
│       ├── cloud-test.yml
│       ├── setup-base.yml
│       ├── setup-nginx-cloud.yml
│       ├── setup-nginx-music.yml
│       ├── setup-velocity.yml
│       └── setup-wireguard.yml
└── roles
    ├── base
    │   ├── defaults
    │   │   └── main.yml
    │   ├── files
    │   │   └── motd.tresor
    │   ├── handlers
    │   │   └── main.yml
    │   ├── tasks
    │   │   ├── main.yml
    │   │   └── verify.yml
    │   └── templates
    │       ├── 50-unattended-upgrades.j2
    │       ├── 99-tresor.conf.sysctl.j2
    │       ├── fail2ban_jail.local.j2
    │       ├── sshd_99-tresor.conf.j2
    │       └── sudoers_ansible.j2
    ├── bday-notifier
    │   ├── defaults
    │   │   └── main.yml
    │   ├── files
    │   │   └── bday_notifier.py
    │   ├── tasks
    │   │   └── main.yml
    │   └── templates
    │       ├── bday-notifier.cron.j2
    │       ├── bday-notifier.env.j2
    │       ├── bday-notifier.logrotate.j2
    │       ├── bday-notifier-run.sh.j2
    │       ├── bday_notifier.py.j2
    │       └── birthdays.yml.j2
    ├── cloudflared
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   │   └── main.yml
    │   ├── meta
    │   │   └── main.yml
    │   ├── tasks
    │   │   ├── main.yml
    │   │   └── status.yml
    │   ├── tests
    │   │   ├── inventory
    │   │   └── test.yml
    │   └── vars
    │       └── main.yml
    ├── content-notifier
    │   ├── defaults
    │   │   └── main.yml
    │   ├── files
    │   │   └── content_notifier.py
    │   ├── handlers
    │   ├── tasks
    │   │   └── main.yml
    │   └── templates
    │       ├── content-notifier.cron.j2
    │       ├── content-notifier.env.j2
    │       ├── content-notifier.logrotate.j2
    │       └── content-notifier.sh.j2
    ├── docker
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   │   └── main.yml
    │   ├── meta
    │   │   └── main.yml
    │   ├── tasks
    │   │   ├── main.yml
    │   │   └── verify.yml
    │   ├── templates
    │   │   └── daemon.json.j2
    │   ├── tests
    │   │   ├── inventory
    │   │   └── test.yml
    │   └── vars
    │       └── main.yml
    ├── docker-firewall
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   │   └── main.yml
    │   ├── meta
    │   │   └── main.yml
    │   └── tasks
    │       └── main.yml
    ├── filebrowser
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   │   └── main.yml
    │   ├── meta
    │   │   └── main.yml
    │   ├── tasks
    │   │   └── main.yml
    │   ├── tests
    │   │   ├── inventory
    │   │   └── test.yml
    │   └── vars
    │       └── main.yml
    ├── filebrowser-public
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   │   └── main.yml
    │   ├── meta
    │   │   └── main.yml
    │   └── tasks
    │       └── main.yml
    ├── grafana
    │   ├── defaults
    │   │   └── main.yml
    │   ├── tasks
    │   │   ├── main.yml
    │   │   └── verify.yml
    │   └── templates
    │       └── datasource.yml.j2
    ├── jellyfin
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   │   └── main.yml
    │   ├── meta
    │   │   └── main.yml
    │   ├── tasks
    │   │   └── main.yml
    │   ├── tests
    │   │   ├── inventory
    │   │   └── test.yml
    │   └── vars
    │       └── main.yml
    ├── jellyfin-music
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   ├── meta
    │   │   └── main.yml
    │   └── tasks
    │       └── main.yml
    ├── kiwix
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   ├── tasks
    │   │   └── main.yml
    │   └── templates
    ├── motd
    │   └── templates
    │       └── 10-tresor.j2
    ├── networks
    │   └── tasks
    │       └── main.yml
    ├── nginx-music
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   │   └── main.yml
    │   ├── tasks
    │   │   ├── cloud.yml
    │   │   └── main.yml
    │   └── templates
    │       ├── cloud.http.nginx.j2
    │       ├── cloud.tls.nginx.j2
    │       ├── cloud-zones.conf.j2
    │       ├── music.http.nginx.j2
    │       ├── music.nginx.j2
    │       ├── music.tls.nginx.j2
    │       └── nginx.conf.j2
    ├── paper
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   │   └── main.yml
    │   ├── tasks
    │   │   └── main.yml
    │   └── templates
    │       ├── paper-global.yml.j2
    │       └── server.properties.j2
    ├── prometheus
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   │   └── main.yml
    │   ├── tasks
    │   │   ├── main.yml
    │   │   └── verify.yml
    │   └── templates
    │       └── prometheus.yml.j2
    ├── steam-free-notifier
    │   ├── files
    │   │   └── bot.py
    │   ├── handlers
    │   │   └── main.yml
    │   ├── tasks
    │   │   └── main.yml
    │   └── templates
    │       └── steam-free-notifier.cron.j2
    ├── traefik
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   │   └── main.yml
    │   ├── meta
    │   │   └── main.yml
    │   ├── tasks
    │   │   ├── main.yml
    │   │   └── status.yml
    │   ├── templates
    │   │   ├── middlewares.yml.j2
    │   │   └── traefik.yml.j2
    │   ├── tests
    │   │   ├── inventory
    │   │   └── test.yml
    │   └── vars
    │       └── main.yml
    ├── uptime-kuma
    │   ├── defaults
    │   ├── tasks
    │   │   └── main.yml
    │   └── templates
    ├── velocity
    │   ├── defaults
    │   │   └── main.yml
    │   ├── handlers
    │   │   └── main.yml
    │   ├── tasks
    │   │   └── main.yml
    │   └── templates
    │       ├── servers.toml.j2
    │       ├── velocity.service.j2
    │       └── velocity.toml.j2
    ├── wireguard-client
    │   ├── defaults
    │   ├── handlers
    │   │   └── main.yml
    │   ├── tasks
    │   │   └── main.yml
    │   └── templates
    │       └── wg0.conf.j2
    └── wireguard-server
        ├── defaults
        │   └── main.yml
        ├── handlers
        │   └── main.yml
        ├── tasks
        │   └── main.yml
        └── templates
            └── wg.conf.j2
```
