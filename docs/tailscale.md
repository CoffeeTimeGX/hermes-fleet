# Tailscale

## What it is

[Tailscale](https://tailscale.com/) builds a private network, called a *tailnet*, out of
your own devices. Each device gets a fixed address in the `100.x.y.z` range and a name,
and the devices talk to each other directly over encrypted WireGuard connections,
wherever they are. Tailscale's servers only help the devices find each other; your
traffic does not pass through them except as an encrypted relay of last resort.

For the fleet this means:

- your PC reaches `vps1` to `vps5` by name, from home or anywhere else,
- the VPSs need no open SSH port on the internet (see [Close public SSH](vps/lockdown.md)),
- the access policy below lets your devices reach the VPSs, and stops the VPSs from
  reaching your PC or each other.

The free Personal plan is enough for the fleet.

## 1. Create your tailnet

Sign up at [tailscale.com](https://tailscale.com/), install the app on your PC (the
Windows installer already did) and sign in. Installing it on your phone too is handy:
you can then SSH into a VPS from the phone in an emergency.

## 2. Check that MagicDNS is on

In the [admin console](https://login.tailscale.com/admin/dns), open **DNS** and check that
**MagicDNS** is enabled (it is, for new tailnets). The inventory reaches each VPS by its
plain name (`host = vps1`), which works through MagicDNS. If you turn it off, put each
VPS's `100.x.y.z` address in `host` instead.

## 3. Paste the fleet access policy

In the admin console, open **Access controls**, switch to the **JSON editor**, replace the
default policy with the contents of
[`home/tailscale-policy.example.hujson`](https://github.com/CoffeeTimeGX/hermes-fleet/blob/main/home/tailscale-policy.example.hujson)
and save. It:

- defines the tag `tag:fleet`, which every VPS gets when it joins,
- lets your own devices reach each other, and SSH (port 22) on every fleet VPS,
- gives the VPSs no access to anything, so a compromised VPS could not reach your PC.

## 4. Create an auth key for the VPSs

`fleet bootstrap` uses an auth key to join each new VPS to your tailnet without you
having to sign in on it. In the admin console, open **Settings > Keys** and choose
**Generate auth key**:

| Setting | Value | Why |
| --- | --- | --- |
| Reusable | on | one key for all five VPSs |
| Ephemeral | off | the VPSs must stay in the tailnet when offline |
| Pre-approved | on (if shown) | no manual approval for each VPS |
| Tags | `tag:fleet` | the access policy applies to them |
| Expiration | up to 90 days | you only need it while setting VPSs up |

Copy the key (`tskey-auth-...`) into the secrets file on your PC,
`~/.config/fleet/secrets/tailscale.env`:

```
TS_AUTHKEY=tskey-auth-...
```

Devices that join with a tagged key do not have to sign in again later: key expiry is
off for tagged devices by default. When the auth key itself expires, only adding a new
VPS needs a new one.

## 5. After bootstrap

Each VPS shows up in the admin console's **Machines** list under its fleet name, tagged
`tag:fleet`, and `fleet ping vps1` works from your PC. The bootstrap script also:

- opens UDP port 41641 on the VPS so connections can be direct instead of relayed,
- leaves the VPS's DNS settings alone (`--accept-dns=false`),
- trusts the `tailscale0` network interface in the VPS's firewall.

The fleet uses ordinary SSH keys over Tailscale, not the separate *Tailscale SSH*
feature.

## Troubleshooting

- `fleet doctor` says Tailscale is not `Running`: open the Tailscale app and sign in.
- `vps1` does not resolve: check MagicDNS (step 2), and that the VPS appears as
  connected in the admin console. Then follow [VPS unreachable](runbooks/vps-unreachable.md).
- To remove a VPS from the fleet for good, also remove its machine in the admin console.
