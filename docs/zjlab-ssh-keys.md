# zjlab SSH authorized_keys inventory

**Created**: 2026-09-09 (R6.98 audit)
**Server**: zjlab (bastion 192.168.10.10:60022 -> target)
**User**: zjlab
**Source**: `/home/zjlab/.ssh/authorized_keys` (read 2026-09-09)

## Purpose

This document inventories every public key fingerprint authorized to log in to zjlab via SSH. Per zjlab-ssh-key-inventory iron rule (added R6.98), this MUST be updated on every key add/remove.

WARNING: This is a server-side ACL inventory. Sync-to-zjlab.py does NOT manage these keys (they are server-only host ACL). Adding a key here requires manual SSH to zjlab by an existing authorized party.

## Authorized keys (9 entries)

| # | Type | Fingerprint (SHA256) | Comment | Owner |
|---|---|---|---|---|
| 1 | RSA | dZphWRxfSkcVoMbbNq5VYuQ4rSKeDkryD+jbinT9yPk | zjlab@ops-astronomy-03 | (see notes) |
| 2 | RSA | Dh8zPkoLi/5sMElDdBWMzJ5mP0InB/PdFZUvuN+mQYU | zjlab@ops-astronomy-02 | (see notes) |
| 3 | RSA | tu2LqX262DWlrPTpRaBYdcFQ8mQjj8M3MF0uNokxKFw | yfanxiao@Computingastronomy | yfanxiao |
| 4 | ED25519 | F+2EgFDj9cYF0/k/rdetrJjIJ6me40ACUkkgQs10KIs | whiteblue616@icloud.com | whiteblue616 |
| 5 | RSA | 8dfPERvsVqv1NnSmH3Lx+klWWVVhwLYB0LxsU04ta5w | m@localhost.localdomain | (legacy m) |
| 6 | RSA | jGLcBQK5zCNAk2+gOwgGXQ3tcupCLY8Z0BMWf5mdyP4 | kyn@storeastronomy | kyn |
| 7 | RSA | i8i+WFAq7LKwnaRLkVSeBMM+h4EtuQ4vRAU03M5M7AA | chenlei154@zhejianglab.com | chenlei154 |
| 8 | ED25519 | Hw5Lh3sekuW2uJmqhRAnj2aSw+5wevmVUsID/7oilKQ | chenlei154@zhejianglab.com | chenlei154 |
| 9 | ED25519 | hyjU5L9kSUh2rOdDYIvBiBAFtiP0bag3FkMC5EXtaMQ | kyn@zjlab.com | kyn |

## Other SSH files in /home/zjlab/.ssh/

| File | Description | Action |
|---|---|---|
| `id_rsa` | zjlab's default private key (Jun 2023) | Used for outbound SSH from zjlab |
| `id_rsa.pub` | matching public key | (auto-generated) |
| `known_hosts` | SSH host key cache | (auto-generated) |
| `known_hosts.old` | previous known_hosts | (rotate periodically) |
| `serveo_key` | Private key for serveo.net tunnel | Used for demo tunnels |
| `serveo_key.pub` | matching public key | (auto-generated) |
| `client.key` | **Backend SSH key for prod** (gw-backend outbound to internal services) | Synced via `_sync_config_certs()`; chmod 600 + chown zjlab:zjlab enforced per zjlab-private-key-mode. **Rotated separately from `id_rsa`; if either side is compromised, rotate this one first.** |

## Offboarding checklist

When a developer leaves the team:
1. Identify their keys by comment field (e.g., `yfanxiao@Computingastronomy`)
2. SSH to zjlab as a still-authorized user
3. Remove the matching line(s) from `/home/zjlab/.ssh/authorized_keys`
4. Update this inventory (remove the row, decrement count)
5. Commit the updated inventory to git

## Iron rules

- zjlab-ssh-key-inventory (R6.98) - MUST be updated on every key change.
- protect-user-config - `.ssh/` is user config; sync-to-zjlab.py does NOT touch it.

## How to update

```bash
# SSH to zjlab (as still-authorized user)
ssh zjlab

# View current authorized_keys (as zjlab)
cat ~/.ssh/authorized_keys

# For each new key, get its fingerprint:
ssh-keygen -lf /path/to/newkey.pub

# Manually edit authorized_keys to add/remove lines
nano ~/.ssh/authorized_keys

# Update this inventory doc and commit
```

## Cross-references

- r698-summary - R6.98 audit origin
- protect-user-config - .ssh/ is user-controlled
- STATE_SNAPSHOT.md section 45.84 - full audit findings