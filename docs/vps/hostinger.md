# Create the VPSs on Hostinger

The fleet has five VPSs, `vps1` to `vps5`, each in its own Hostinger account. Do these
steps once per account. You need your **fleet public key** (the `ssh-ed25519 ...` line
the installer printed; print it again with `cat ~/.ssh/fleet_ed25519.pub`).

## Choose a plan

Video work needs memory and CPU. Hostinger's KVM plans, and how many Claude sessions
each comfortably runs at the same time:

| Plan | vCPU | RAM | Disk | Sessions at once |
| --- | --- | --- | --- | --- |
| KVM 1 | 1 | 4 GB | 50 GB | not recommended for video |
| KVM 2 | 2 | 8 GB | 100 GB | 1 |
| KVM 4 | 4 | 16 GB | 200 GB | 2 |
| KVM 8 | 8 | 32 GB | 400 GB | 3 or 4 |

Check hPanel for the current figures. Start with `sessions = 1` in the inventory and raise
it once you have seen how heavy your videos are (`fleet status` shows load and free
memory).

Any data center works. The sessions talk mostly to Anthropic's API, so the location
makes little difference to them; one near you makes SSH a little snappier.

## Set up each VPS

1. Sign in to the Hostinger account and buy the VPS plan.
2. When asked for the operating system, choose **Plain OS** and then **Ubuntu 24.04**.
   Do not pick a template with a control panel or preinstalled apps: the bootstrap
   script expects a clean system.
3. Set a strong **root password** and keep it in your password manager. The fleet never
   uses it, but it is your way in through Hostinger's Web Console in an emergency.
4. When asked for an **SSH key**, paste your fleet public key. If you missed that step,
   add it afterwards: *VPS > Manage > Settings > SSH keys > Add SSH key*.
5. Leave the hostname as it is. The bootstrap renames the VPS to `vps1` and so on.
6. If you use hPanel's own **firewall** for this VPS, allow TCP port 22 (until you close
   public SSH) and UDP port 41641 (Tailscale). With no hPanel firewall rules, there is
   nothing to do: the VPS gets its own firewall during bootstrap.
7. On the VPS's **Overview** page, copy its public IPv4 address.

## Write it into your inventory

Open your inventory, `~/.config/fleet/fleet.ini`, and fill in `public_ip` for the node.
Use `hostinger_account` as a reminder of which Hostinger login owns it:

```ini
[vps1]
host = vps1
public_ip = 203.0.113.10
hostinger_account = hostinger-account-1
providers = claude
sessions = 1
channels = all
enabled = true
```

Keep a fixed pairing: Hostinger account 1 holds `vps1`, account 2 holds `vps2`, and so
on, and each VPS gets its own Claude account as well. Your inventory stays on your PC; it
is never part of the repository.

Next: [Provision a VPS](provisioning.md).
