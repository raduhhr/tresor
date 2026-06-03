# Sanitization

This repository is public by design. It should prove the engineering work
without exposing the live system.

## Never Publish

- Real `ansible/inventory/` files
- Vault files with real encrypted payloads
- Vault password files
- `.env` files
- API tokens, Discord webhooks, Cloudflare tunnel tokens, cookies, SSH keys,
  WireGuard private keys, database passwords, R2 credentials
- Database dumps, runtime exports, browser session data, or generated state
- Private machine names beyond generic role names

## Safe To Publish

- Role and playbook structure
- Templates that read secrets from variables or environment variables
- Placeholder examples
- Public architecture summaries
- Public screenshots already used as portfolio evidence
- Documentation that describes boundaries without giving usable credentials

## Local Preflight

Run:

```bash
scripts/sanity.sh
```

Then run a manual pattern scan for obvious mistakes:

```bash
rg -n --hidden -g '!/.git/' 'discord.com/api/webhooks|BEGIN .*PRIVATE KEY|ANSIBLE_VAULT|PASSWORD=|TOKEN=|SECRET=' .
```

Any hit should be reviewed before pushing.
