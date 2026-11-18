---
name: fleet-provision
description: Set up, repair or extend fleet VPSs. Bootstrap a fresh Hostinger VPS, join it to Tailscale, close public SSH, install or update Claude Code, push credentials and sync worker code.
version: 1.2.0
metadata:
  hermes:
    tags: [fleet, provisioning, hostinger, tailscale, claude-code]
    category: fleet
    requires_toolsets: [terminal]
---

# Fleet provisioning

## When to use
"Set up vps3", "I rebuilt vps2 on Hostinger", "install Claude on the VPSs", "update
Claude Code everywhere", "new API key for vps4", "add a sixth VPS".

## New or rebuilt VPS
Follow `docs/vps/provisioning.md` in the fleet repository. In short:
1. Confirm with the owner: node name, Hostinger account, public IP, and that the VPS
   was created with the fleet SSH key (`~/.ssh/fleet_ed25519.pub`) and Ubuntu 24.04.
2. Put `public_ip` under the node's section in `~/.config/fleet/fleet.ini`. For a
   rebuilt VPS, also run `fleet forget-host <vps>`.
3. `fleet bootstrap <vps> --public` (root over the public IP, about 5 minutes).
4. `fleet ping <vps>` must work over Tailscale (host = the node name).
5. `fleet lockdown <vps>` closes public SSH. Ask the owner first.
6. `fleet provider install claude <vps>`
7. `fleet secrets push claude <vps>`. The file `~/.config/fleet/secrets/<vps>/claude.env`
   must already be filled in by the owner; if it is not, ask them to do it.
8. `fleet provider check claude <vps> --smoke` must print `smoke: ok`.
9. `fleet status <vps>` must show the service active and `claude:ok`.

## Updates
- Worker or adapter code changed in the repository: `git pull` in the repo, then
  `fleet sync`. Running jobs keep running.
- Update Claude Code: `fleet provider install claude all` (add `--version <x.y.z>` to
  pin one version), then `fleet provider check claude all`.
- New credentials: the owner updates `~/.config/fleet/secrets/<vps>/claude.env`; then
  `fleet secrets push claude <vps>` and a `--smoke` check.
- More sessions on a VPS: change `sessions` in `fleet.ini`, then
  `fleet bootstrap <vps> --skip-upgrade`.

## Pitfalls
- `--public` is only for the first bootstrap. Afterwards the node is reached by its
  Tailscale name.
- Never run `fleet lockdown` before `fleet ping <vps>` works over Tailscale.
- Locked out: the owner opens the VPS in Hostinger hPanel, clicks "Web console" on the
  Overview page, and runs `bash /home/fleet/fleet/app/lockdown.sh --undo`.
- Claude Code refuses unattended mode as root, so providers always run as `fleet`.
- A subscription token from `claude setup-token` expires after a year; `fleet health`
  warns about a month before.

## Verification
`fleet health` lists no problems for the node, and the `--smoke` check passes.
