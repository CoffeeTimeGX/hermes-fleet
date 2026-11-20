# Rebuild a VPS

Use this when a VPS is broken beyond repair, may have been compromised, or you simply
want it clean. A VPS holds nothing that cannot be recreated: its code comes from the
repository, its Claude credential from your PC. A rebuild takes about fifteen minutes,
most of it package installs.

What is lost in a rebuild is what the VPS has not handed over yet: finished jobs that
are not pulled, and jobs still waiting in its queue. Steps 1 and 2 save them.

The examples use `vps3`.

## 1. Save the finished work

If the VPS is still reachable:

```
fleet pause vps3 --reason "rebuild"
fleet pull vps3
```

If a job is still running and you want its result, wait for it (`fleet jobs vps3`), then
pull again.

If the VPS is not reachable and its unpulled results matter, use Hostinger's Emergency
mode to copy them out first (see [Close public SSH](../vps/lockdown.md#locked-out)), or
take a snapshot in hPanel (*Backups & Monitoring > Snapshots & Backups*) that you can
come back to.

## 2. Save the queue

Copy the jobs that wait in the VPS's queue to your PC, so that they survive the rebuild:

```
mkdir requeue
scp "vps3:/home/fleet/fleet/jobs/inbox/*.json" requeue/
```

If the VPS is not reachable, Hermes can tell you which jobs were queued there from its
own conversation, or you can write them again.

If another VPS should make them while vps3 is rebuilt, move them there instead, while
vps3 still answers: `fleet handover vps3 vps4`. Then skip step 6.

## 3. Reinstall the system in hPanel

1. Sign in to the Hostinger account that owns the VPS and open it (**Manage**).
2. In the sidebar, open **OS & Panel > Operating System**.
3. Choose **Plain OS**, then **Ubuntu 24.04**, and press **Change OS**. If it asks for a
   root password or an SSH key, give a new strong password and your fleet public key.

This erases the whole disk.

## 4. Clean up the old identity

In the [Tailscale admin console](https://login.tailscale.com/admin/machines), remove the
old `vps3` machine. Otherwise the rebuilt VPS joins as `vps3-1` and `fleet` cannot find
it.

On your PC, forget the old SSH host keys:

```
fleet forget-host vps3
```

## 5. Provision it again

Follow [Provision a VPS](../vps/provisioning.md) from step 1, with `vps3`. If the public
IP address changed, update `public_ip` in your inventory first. The Claude credential in
`~/.config/fleet/secrets/vps3/claude.env` is still valid: the same account keeps the same
VPS, and step 6 pushes it again.

If your Tailscale auth key has expired since the first setup, make a new one first
([Tailscale, step 4](../tailscale.md#4-create-an-auth-key-for-the-vpss)).

## 6. Put the saved jobs back

```
fleet dispatch requeue/*.json
```

They keep their ids and go back to the VPS that makes their channel, the rebuilt one.
Delete the `requeue` folder afterwards.

## 7. Check

```
fleet status vps3
fleet health
fleet dispatch jobs/examples/hello-fleet.json --to vps3
```

When the test job is `done`, the VPS is back in the fleet.

## Replacing a VPS with a bigger one

A move to a bigger plan inside the same Hostinger account usually keeps the system and
needs no rebuild: upgrade it in hPanel, then raise `sessions` in your inventory and run
`fleet bootstrap vps3 --skip-upgrade`. A move to a brand-new VPS is a rebuild: follow
this page, with the new VPS's public IP in your inventory.
