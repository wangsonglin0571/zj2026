# Sync Notes

This project is synced between:

- MacBook Pro: `/Users/wangsonglin/zj2026/`
- Mac mini: `/Users/wangsonglin/zj2026/`

## Preferred Commands

Run these on the MacBook Pro.

```bash
zj-check      # Check SSH connection to Mac mini
zj-dry        # Preview MacBook Pro -> Mac mini sync
zj-sync       # Sync MacBook Pro -> Mac mini, excluding .venv
zj-pull-dry   # Preview Mac mini -> MacBook Pro sync
zj-pull       # Pull Mac mini -> MacBook Pro, excluding .venv
```

Full script:

```bash
sync-zj2026 --help
```

## Direction

Default direction is MacBook Pro to Mac mini:

```bash
sync-zj2026 --exclude-venv
```

Reverse direction is Mac mini to MacBook Pro:

```bash
sync-zj2026 --pull --dry-run --exclude-venv
sync-zj2026 --pull --exclude-venv
```

## Why Exclude `.venv`

`.venv/` contains many small machine-local files. It is slow to sync and can be rebuilt locally. Keep source files, assets, and release files synced; rebuild Python environments per machine when needed.

## SSH Details

Known working Mac mini target:

```text
wangsonglin@192.168.124.35:/Users/wangsonglin/zj2026/
```

SSH key on MacBook Pro:

```text
/Users/wangsonglin/.ssh/id_ed25519_macmini
```

Expected Mac mini host key fingerprint:

```text
SHA256:Q0+GSiOFnawfGjPBd9DkIYYnpkQxVYOb9/DgQKFb+XY
```

## Troubleshooting

If SSH or rsync mentions `198.18.0.21`, the command is not using the fixed LAN IP path. Use:

```bash
sync-zj2026 --check
```

If the Mac mini IP changes, update:

```text
/Users/wangsonglin/.codex/skills/macmini-sync/scripts/sync-zj2026.sh
/Users/wangsonglin/.ssh/config
```

