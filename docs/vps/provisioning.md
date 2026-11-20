# Provision a VPS

This turns a fresh Hostinger VPS into a fleet node. It takes about ten minutes per VPS,
most of it waiting for package installs. You can run the commands yourself or ask Hermes:
*"Set up vps1: bootstrap it, check it over Tailscale, lock it down, install Claude and run
the smoke check."* Hermes follows the same steps and asks before closing public SSH.

Before you start, have:

- the VPS created with Ubuntu 24.04 ([Create the VPSs](hostinger.md)),
- its `public_ip` and its channel (`channels`) in `~/.config/fleet/fleet.ini`,
- `TS_AUTHKEY` in `~/.config/fleet/secrets/tailscale.env` ([Tailscale](../tailscale.md)),
- the Claude credential for this VPS ([Claude accounts](../providers/claude-accounts.md#get-a-token-for-each-vps)).

The examples use `vps1`.

## 1. Get the fleet key onto the VPS

Every `fleet` command logs in with your fleet SSH key, so root on the new VPS must
accept it. If you pasted the key while creating the VPS, check that it works:

```
ssh -i ~/.ssh/fleet_ed25519 root@203.0.113.10 echo ok
```

(Use the VPS's public IP. Answer `yes` to the host key question.) If it prints `ok`, go
to step 2. If it asks for a password or says *Permission denied*, add the key in one of
these ways:

=== "Hostinger Web Console"

    In hPanel, open the VPS, click **Web Console** on its Overview page and run, with
    your own public key line:

    ```bash
    mkdir -p ~/.ssh && chmod 700 ~/.ssh
    echo 'ssh-ed25519 AAAA...your key... hermes-fleet@your-pc' >> ~/.ssh/authorized_keys
    chmod 600 ~/.ssh/authorized_keys
    ```

=== "Root password, Windows"

    ```powershell
    type $HOME\.ssh\fleet_ed25519.pub | ssh root@203.0.113.10 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
    ```

=== "Root password, Linux or macOS"

    ```bash
    ssh-copy-id -i ~/.ssh/fleet_ed25519.pub root@203.0.113.10
    ```

Then run the `echo ok` check again.

## 2. Bootstrap

```
fleet bootstrap vps1 --public
```

`--public` connects to the public IP, because the VPS is not on Tailscale yet. The script
runs as root and prints each step. It:

- renames the VPS to `vps1` and keeps its clock on UTC,
- installs all OS updates, then the tools the sessions use: ffmpeg, ImageMagick, fonts,
  Python, git, jq, rsync and build tools,
- adds a 4 GB swap file if the VPS has less than 8 GB of memory, and caps the system
  journal at 500 MB,
- creates the unprivileged `fleet` user, which may start, stop and restart its own
  service and do nothing else as root,
- allows SSH keys only (no passwords), turns on fail2ban and automatic security updates,
- joins your tailnet as `vps1` with the tag `tag:fleet`,
- turns on the firewall: everything from Tailscale is allowed, public SSH stays open
  (keys only, rate limited) until you close it in step 4,
- installs the job worker as the `fleet-worker` service and a nightly cleanup timer.

It ends with a summary like this:

```
node:          vps1
tailscale:     100.101.102.103 (Running)
worker:        active (version 1.4.0)
parallel jobs: 1
public ssh:    open, keys only and rate limited, until fleet lockdown
reboot needed: no
next:          fleet ping vps1, then fleet lockdown vps1, then fleet provider install claude vps1
```

The bootstrap is safe to run again. Options: `--skip-upgrade` skips the full OS upgrade
(quicker re-runs), and `--tz Europe/Paris` sets another clock for the VPS.

## 3. Check it over Tailscale

```
fleet ping vps1
```

It must print `vps1 ok` and a time in milliseconds. This connection goes over Tailscale
as the `fleet` user, the way every later command will. If it fails, do not continue: see
[VPS unreachable](../runbooks/vps-unreachable.md).

## 4. Close public SSH

```
fleet lockdown vps1
```

From now on the VPS answers SSH only over Tailscale. See [Close public SSH](lockdown.md),
including how to undo it.

## 5. Install Claude Code

```
fleet provider install claude vps1
```

This installs Claude Code for the `fleet` user with Anthropic's installer, on the stable
release channel, and turns off its self-updates so all five VPSs stay on one version.
See [Claude Code on the VPSs](../providers/claude.md).

## 6. Push the Claude credential

Put this VPS's token in `~/.config/fleet/secrets/vps1/claude.env` on your PC (the file
explains both options), then:

```
fleet secrets push claude vps1
```

It prints the names of the values it pushed, never the values.

## 7. Smoke test

```
fleet provider check claude vps1 --smoke
```

This runs one tiny Claude session on the VPS. Look for `smoke: ok`. If it fails, the
message says why (most often a mistyped token).

## 8. Check the node

```
fleet status vps1
```

The `SERVICE` column must say `active` and `PROVIDERS` must say `claude:ok`. `fleet health`
should list no problem for `vps1`.

`fleet list` shows the channel each VPS makes videos for. Once the node is ready,
`fleet dispatch` sends that channel's jobs to it.

Repeat for `vps2` to `vps5`. Steps 5 to 8 also accept `all` (or a list such as
`vps2,vps3`) once those VPSs are bootstrapped.

## Later changes

- **More sessions on a VPS:** change `sessions` for it in `fleet.ini`, then run
  `fleet bootstrap vps1 --skip-upgrade` (over Tailscale, without `--public`).
- **Another channel for a VPS:** change `channels` for it in `fleet.ini`. It applies to
  the next `fleet dispatch`; jobs already queued stay where they are (`fleet handover`
  moves them).
- **A rebuilt VPS:** see [Rebuild a VPS](../runbooks/rebuild-vps.md).
- **New code from the repository:** see [Updates](../operations/updates.md).
