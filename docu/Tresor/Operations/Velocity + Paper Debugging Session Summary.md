# Velocity + Paper Debugging Session Summary

## Setup

- **VPS** (tresor-vps): Velocity proxy, public-facing, systemd service
- **Tresor** (home server): Paper MC in Docker (itzg/minecraft-server), behind WireGuard
- **WireGuard tunnel**: VPS = 10.66.66.1, Tresor = 10.66.66.2
- **Forwarding mode**: modern (Velocity → Paper)

* * *

## Two Errors Encountered

### Error 1: "This server requires you to connect with Velocity"

**Source**: Paper is rejecting the connection because Velocity is not sending modern forwarding headers.  
**Meaning**: Velocity is running with `mode = "none"` (forwarding disabled), so Paper sees a raw connection without forwarding headers and rejects it.

### Error 2: "Failed to log in: Invalid session"

**Source**: Mojang auth / Paper online-mode mismatch.  
**Meaning**: Velocity IS sending forwarding headers correctly, but either the secret doesn't match OR Paper is running with `online-mode=true` and trying to verify the session itself.  
**Note**: Getting Error 2 is actually *progress* — it means forwarding is working.

* * *

## Root Causes Found (in order of discovery)

### 1\. `velocity.toml.j2` missing `mode = "..."` in `[player-info-forwarding]`

The template had `forwarding-secret-file` but no `mode` key. Velocity defaulted to `none`.  
**Fix**: Add `mode = "{{ velocity_forwarding_mode }}"` inside the section.

### 2\. `-Dvelocity.config` JVM flag pointed to wrong path

`velocity.service.j2` had `-Dvelocity.config={{ velocity_home }}/velocity.toml` but Ansible was rendering the config to `{{ velocity_home }}/config/velocity.toml`. Velocity ignored the flag and read whichever file it found.  
**Fix**: Align the `-D` flag path with the actual rendered dest, or drop the flag and render to the working directory root.

### 3\. Velocity 3.4.0-SNAPSHOT `ForwardingMigration` bug

This SNAPSHOT build runs a migration on startup that rewrites the config. It detected the Ansible-rendered format as "old", rewrote `mode` to `none` in memory, ran with forwarding disabled, then saved the "migrated" file back to disk. This caused the config to look correct on disk but run with `none` in memory — extremely confusing to debug.  
**Fix**: Use the old-format top-level key `player-info-forwarding-mode = "MODERN"` instead of the `[player-info-forwarding]` section format. This avoids triggering the migration entirely.

### 4\. `config-version = "2.7"` conflicts with old-format key

Adding `config-version = "2.7"` tells Velocity the config is new format, so it looks for `[player-info-forwarding]` section — but the template was using the old-format top-level key. Velocity ignored it.  
**Fix**: Remove `config-version` when using the top-level key format.

### 5\. Mismatched forwarding secrets across two separate vaults

The project has two Ansible vaults — one for VPS (`tresor-vps`) and one for Tresor. The `vault_velocity_forwarding_secret` was rotated in the Tresor vault but not the VPS vault, so:

- Paper had `b52b3e...`
- Velocity `forwarding.secret` had `2214...`

**Fix**: Update both vaults to the same value. Long-term: move `vault_velocity_forwarding_secret` to a shared `group_vars/all/vault.yml`.

### 6\. Paper is running in Docker, not systemd

All `journalctl -u paper` calls returned nothing. Paper logs are at `docker logs paper`.  
The itzg image copies `/config/*` → `/data/config/*` **on every startup**, meaning the overlay mount at `/config/paper-global.yml` overwrites `/data/config/paper-global.yml` each restart.  
Edits to `/mnt/ssd/services/paper/config/paper-global.yml` (the `/data` bind mount) were being overwritten by the overlay on restart.  
**Fix**: Edit `/mnt/ssd/services/paper/config-overlay/paper-global.yml` — that's the file mounted at `/config/paper-global.yml` inside the container and is the authoritative source.

### 7\. Velocity validation task checking wrong path

After moving the render dest, the validate shell task still grepped the old path and failed. Also the grep pattern was wrong after switching to the old-format key.  
**Fix**: Keep dest and validation path in sync; update grep to match `^player-info-forwarding-mode\s*=\s*"MODERN"`.

* * *

## Current State

### Velocity (`/opt/velocity/velocity.toml`)

```toml
player-info-forwarding-mode = "MODERN"
forwarding-secret-file = "/opt/velocity/forwarding.secret"
```

Forwarding secret: `REDACTED'

### Paper (`/data/config/paper-global.yml` inside container)

```yaml
proxies:
  velocity:
    enabled: true
    online-mode: false
    secret: REDACTED
```

### Secrets: ✅ Match

### No more Error 1, server up and running. 

