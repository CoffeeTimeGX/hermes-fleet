# Close public SSH

After the bootstrap, a VPS still accepts SSH on its public address (keys only, rate
limited), because that is how the first connection reached it. Once SSH works over
Tailscale, close it:

```
fleet lockdown vps1
```

The VPS then answers SSH only over Tailscale, from your own devices. Port scanners and
password guessers on the internet find nothing to talk to.

## What it does

`fleet lockdown` logs in as root over Tailscale and runs `lockdown.sh` on the VPS, which:

1. refuses to do anything unless Tailscale is running on the VPS and has an address,
2. refuses if your own connection does not come from a Tailscale address, so you cannot
   cut off the connection you are using,
3. removes every firewall rule that opens port 22 (IPv4 and IPv6) and keeps the
   `tailscale0` interface open,
4. remembers the lockdown in `/etc/fleet/locked-down`, so a later bootstrap re-run keeps
   SSH closed.

Hermes asks you before it runs a lockdown, and never before `fleet ping` works over
Tailscale.

## Undo

```
fleet lockdown vps1 --undo
```

This opens public SSH again (keys only, rate limited). You need it only to repair
Tailscale on that VPS.

## Locked out

If Tailscale stops working on a VPS that is locked down, `fleet` cannot reach it. The VPS
still runs its jobs; you just cannot talk to it. To get back in:

1. In hPanel, open the VPS and click **Web Console** on its Overview page. It opens a
   root terminal in your browser; Hostinger's own troubleshooting guide uses it to
   repair SSH firewall rules. If it asks for a password, it is the root password you
   chose when you created the VPS (you can set a new one on the same page).
2. Run:

    ```bash
    bash /home/fleet/fleet/app/lockdown.sh --undo
    ```

3. From your PC, reach the VPS over its public address and repair Tailscale, for
   example by running the bootstrap again (`fleet bootstrap vps1 --public --skip-upgrade`).
4. When `fleet ping vps1` works again, run `fleet lockdown vps1`.

If even the Web Console does not respond, Hostinger's **Emergency mode** (*VPS > Manage >
Settings > Emergency mode*) starts a rescue system that shows the VPS's files under
`/mnt`. It is meant for rescuing data; [rebuilding the VPS](../runbooks/rebuild-vps.md) is
usually quicker.

[VPS unreachable](../runbooks/vps-unreachable.md) walks through the whole diagnosis.
