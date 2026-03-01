# **Ops Manual – Ansible Quick Commands**

### Deploy or re-deploy a playbook

Run a play on a specific host group:  
`ansible-playbook -i inventory/hosts.ini playbooks/paper/deploy.yml --limit prod/qa/vps`

Run a play on a specific host:  
`ansible-playbook -i inventory/hosts.ini playbooks/paper/deploy.yml --limit tresor/tresor-vm/tresor-vps`  
Or multiple roles sequentially:  
`ansible-playbook -i inventory/hosts.ini \ playbooks/{traefik,cloudflared,prometheus,grafana}/deploy.yml --limit prod`

Dry-run (no changes, just check what’d happen):  
`ansible-playbook -i inventory/hosts.ini playbooks/deploy.yml --limit prod --check`

Verbose/debug:  
`ansible-playbook -i inventory/hosts.ini playbooks/deploy.yml -vv`

> verbosity ranges from -v to -vvvv (you don't want that)

* * *

### Start / stop / restart containers or services

**Stop** a container (replace `<service>` with e.g. `traefik`, `jellyfin`, `prometheus`):
`ansible-playbook -i inventory/hosts.ini playbooks/<service>/stop.yml --limit tresor`

**Start** a container:
`ansible-playbook -i inventory/hosts.ini playbooks/<service>/start.yml --limit tresor`

**Restart** a container:
`ansible-playbook -i inventory/hosts.ini playbooks/traefik/restart.yml --limit tresor`

Restart with docker_container ad-hoc:  
`ansible tresor -i inventory/hosts.ini -m community.docker.docker_container \ -a "name=traefik state=stopped"`

* * *

### Manage Encrypted Secrets (ansible-vault)

Encrypt a new secret file:

```bash
ansible-vault encrypt group_vars/prod/vault.yml
```

Edit existing vault file (prompts for password):

```bash
ansible-vault edit group_vars/prod/vault.yml
```

View contents (read-only):

```bash
ansible-vault view group_vars/prod/vault.yml
```

Re-encrypt with new password:

```bash
ansible-vault rekey group_vars/prod/vault.yml
```

Use the vault during playbook runs (prompts automatically if needed):

```bash
ansible-playbook -i inventory/hosts.ini playbooks/deploy.yml --ask-vault-pass
```

Or with a local password file (faster automation):

```bash
ansible-playbook -i inventory/hosts.ini playbooks/deploy.yml --vault-password-file ~/.vault_pass.txt
```

* * *

### Ad-hoc commands for live checks

Ping all hosts:

```bash
ansible all -i inventory/hosts.ini -m ping
```

Check disk usage:

```bash
ansible all -i inventory/hosts.ini -a "df -h | grep -E '/$|/mnt'"
```

Check docker status everywhere:

```bash
ansible all -i inventory/hosts.ini -a "docker ps --format 'table {{.Names}}\t{{.Status}}'"
```

* * *

### Troubleshooting & logs

Run a single task from a role:

```bash
ansible-playbook -i inventory/hosts.ini playbooks/grafana/deploy.yml --start-at-task="Run Grafana container"
```

Print variables for a host:

```bash
ansible -i inventory/hosts.ini tresor -m debug -a "var=hostvars['tresor']"
```

Tail container logs remotely:

```bash
ansible tresor -i inventory/hosts.ini -a "docker logs -n 50 prometheus"
```

* * *

### Notes & tips

- Always run playbooks from your project root (`~/Desktop/tresor/ansible`).
    
- Keep vault passwords out of git — use `.vault_pass.txt` locally and gitignore it.
    
- `--limit` can be `tresor`, `tresor-vps`, `prod`, or any group in your inventory.
    
- For testing, use `--limit vm` to target `tresor-vm`.
    

* * *

&nbsp;