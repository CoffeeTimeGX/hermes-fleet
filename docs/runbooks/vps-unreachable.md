# VPS unreachable

**Symptoms:** `fleet health` says `vps3: unreachable (...)`, `fleet status` shows
`UNREACHABLE`, or `fleet ping vps3` fails.

**What it means for the work:** usually less than it seems. Only your PC's connection is
broken. If the VPS itself is up, it keeps running its queue, and everything it finishes
waits there for the next pull. `fleet dispatch` sends new jobs to the other VPSs
meanwhile.

## 1. Is it your PC, or that VPS?

```
fleet ping
```

- **Every VPS fails:** the problem is on your side. Open the Tailscale app on your PC
  and check that it is connected and signed in (`fleet doctor` shows
  `tailscale is Running`). Check your internet connection.
- **Only one fails:** go on with that VPS.

## 2. Read the error

`fleet ping vps3` prints the SSH error. It tells you where to look:

| Error | Likely cause | Go to |
| --- | --- | --- |
| `Could not resolve hostname vps3` | Your PC cannot find the name: MagicDNS is off, or the VPS is not in your tailnet under that name | [Step 3](#3-check-tailscale) |
| `Connection timed out` or `Operation timed out` | The VPS is off or frozen, or Tailscale stopped on it | [Step 3](#3-check-tailscale), then [step 4](#4-check-the-vps-in-hpanel) |
| `Connection refused` | The VPS is up, but its SSH server is not running | [Step 5](#5-look-inside-with-the-web-console) |
| `Permission denied (publickey)` | The VPS no longer accepts the fleet key | [Step 5](#5-look-inside-with-the-web-console) |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` or `Host key verification failed` | The VPS was rebuilt and has a new identity | Run `fleet forget-host vps3`, then `fleet ping vps3` again |

## 3. Check Tailscale

Open the [Machines page](https://login.tailscale.com/admin/machines) of the Tailscale
admin console and find `vps3`.

- **Not listed, or listed as `vps3-1`:** the VPS joined again under another name, or was
  removed. Remove stale entries, then rejoin the VPS as in step 6.
- **Listed but not connected** (it shows when it was last seen): Tailscale on the VPS
  is stopped, or the VPS is down. Go to step 4.
- **Connected:** the VPS and Tailscale are fine. Check MagicDNS (Tailscale's
  [DNS page](https://login.tailscale.com/admin/dns)) and that your inventory says
  `host = vps3` for it. Try `ssh vps3 echo ok` to see the full error.

## 4. Check the VPS in hPanel

Sign in to the **Hostinger account that owns this VPS** (`fleet list` shows which one,
under `ACCOUNT`) and open the VPS.

- **The status is not running:** start it. If the VPS was stopped or suspended because
  of an unpaid invoice, settle it in that account first.
- **It runs but does not respond:** look at the CPU and memory graphs. A VPS that ran
  out of memory can freeze for minutes. Wait five minutes, then press **Reboot** on the
  Overview page. After the reboot, jobs that were running start again by themselves
  (once, by default).

If you set up the [Hostinger API](../home/hostinger-api.md), Hermes can do this check
and the reboot for you; it asks before rebooting.

## 5. Look inside with the Web Console

The Web Console works even when SSH and Tailscale do not. In hPanel, open the VPS and
press **Web console** on its Overview page. It opens a root terminal in your browser.

Check the three services the fleet needs:

```bash
tailscale status
systemctl status ssh --no-pager
systemctl status fleet-worker --no-pager
```

| What you see | Fix |
| --- | --- |
| `tailscale status` says it cannot connect to `tailscaled` | `systemctl restart tailscaled` |
| `tailscale status` says `Tailscale is stopped` | `tailscale up --hostname=vps3 --accept-dns=false` (with this VPS's name) |
| `tailscale status` says `Logged out` or asks you to log in | The VPS lost its place in your tailnet: step 6 |
| `ssh` is not `active (running)` | `systemctl restart ssh` |
| `fleet-worker` is not `active (running)` | `systemctl restart fleet-worker` |

For `Permission denied (publickey)`, check that the fleet key is still there for both
users:

```bash
cat /home/fleet/.ssh/authorized_keys /root/.ssh/authorized_keys
```

Each file must contain your fleet public key (`ssh-ed25519 AAAA... hermes-fleet@...`,
the line in `~/.ssh/fleet_ed25519.pub` on your PC). If it is missing, add it the way
[Provision a VPS, step 1](../vps/provisioning.md#1-get-the-fleet-key-onto-the-vps)
shows, once for each of the two files, and then
`chown fleet:fleet /home/fleet/.ssh/authorized_keys`.

Then try `fleet ping vps3` again from your PC.

## 6. Rejoin Tailscale

When the VPS is up but has lost its Tailscale login, rejoin it with the bootstrap,
which uses the auth key in `~/.config/fleet/secrets/tailscale.env` on your PC. Tailscale
auth keys expire after at most 90 days: if yours has, make a new one first
([Tailscale, step 4](../tailscale.md#4-create-an-auth-key-for-the-vpss)).

1. If the VPS is locked down, open public SSH again from the Web Console:

    ```bash
    bash /home/fleet/fleet/app/lockdown.sh --undo
    ```

2. In the Tailscale admin console, remove the old `vps3` machine, so the VPS gets its
   name back instead of `vps3-1`.
3. From your PC, run the bootstrap over the public address:

    ```
    fleet bootstrap vps3 --public --skip-upgrade
    ```

4. Check it, then close public SSH again:

    ```
    fleet ping vps3
    fleet lockdown vps3
    ```

## 7. When nothing works

If the Web Console does not respond either, use Hostinger's **Emergency mode** to reach
the VPS's files and copy out anything unpulled (see
[Close public SSH](../vps/lockdown.md#locked-out)), or
[rebuild the VPS](rebuild-vps.md). A rebuild takes about fifteen minutes and is often
the quickest way back.

## Afterwards

```
fleet status vps3
fleet pull vps3
fleet health
```

`fleet health` sends a `Resolved` message once the VPS answers again.
