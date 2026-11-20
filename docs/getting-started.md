# Getting started

This page is the whole path from an empty PC to the first finished video, in order.
Each step links to a page with the details. Plan an afternoon for the first VPS; the
other four go much faster.

## What you need

| What | Why | Where |
| --- | --- | --- |
| A Windows, Linux or macOS computer at home | It runs the Hermes director and the `fleet` command | [Windows](home/windows.md), [Linux and macOS](home/linux-macos.md) |
| A Tailscale account (the free Personal plan is enough) | The private network between your PC and the VPSs | [Tailscale](tailscale.md) |
| An account with a model provider for Hermes, such as Nous Portal or OpenRouter | Hermes, the director, runs on a model you choose. It does not use Claude | [Windows step 4](home/windows.md#4-choose-the-directors-model) |
| Five Hostinger accounts, each with one VPS | Where the Claude sessions run | [Create the VPSs](vps/hostinger.md) |
| Five Claude accounts (Pro or Max), one per VPS, or five Console API keys | How each VPS signs in to Claude | [Claude accounts and Anthropic's rules](providers/claude-accounts.md) |
| Telegram on your phone (recommended) | To talk to the director and get its reports anywhere | [Telegram](home/telegram.md) |

!!! warning "Read the Claude accounts page first"
    Running Claude subscriptions around the clock on servers has limits and rules.
    [Claude accounts and Anthropic's rules](providers/claude-accounts.md) explains them in
    plain words, and when to use API keys instead.

## The steps

1. **Set up your home computer.** Run the installer, then check it with `fleet doctor`,
   choose the director's model, connect Telegram and turn on the scheduled checks.
   Follow [Windows](home/windows.md) or [Linux and macOS](home/linux-macos.md).
   The installer prints your **fleet public key**. Keep it at hand for step 3.
2. **Set up Tailscale.** Sign in on your PC, paste the fleet access policy and create
   an auth key for the VPSs. See [Tailscale](tailscale.md).
3. **Create the five VPSs on Hostinger**, one per Hostinger account, with Ubuntu 24.04
   and the fleet public key. Write each public IP address into your inventory file,
   with the channel that VPS makes videos for. See [Create the VPSs on Hostinger](vps/hostinger.md).
4. **Get the Claude credentials** for each VPS and put them in its secrets file. See
   [Claude accounts](providers/claude-accounts.md#get-a-token-for-each-vps).
5. **Provision each VPS** with a handful of `fleet` commands, or ask Hermes to do it:
   *"Set up vps1. Its public IP is in the inventory."* See [Provision a VPS](vps/provisioning.md).
6. **Run a first job** on every VPS:

    ```
    fleet dispatch jobs/examples/hello-fleet.json --to all
    fleet jobs
    fleet pull
    ```

    Run these from the repository folder (`hermes-fleet` in your home folder, unless you
    chose another place). After a minute or two, `fleet jobs` shows them as `done` and
    `fleet pull` downloads each one to `fleet-results/<vps>/<job-id>/` in your home
    folder, with a test video in `output/`.

After that, you mostly talk to Hermes. See [Everyday use](operations/everyday.md).

## Checklist

- [ ] `fleet doctor` passes on your PC
- [ ] The director answers in the terminal (`hermes -p director`) and on Telegram
- [ ] `fleet hermes-cron` created the three scheduled jobs
- [ ] Tailscale: policy pasted, auth key in `secrets/tailscale.env`
- [ ] Five VPSs created with Ubuntu 24.04 and the fleet key, public IPs and channels in
      `fleet.ini` (`fleet list` shows them)
- [ ] Each VPS: bootstrap, ping over Tailscale, lockdown, Claude installed, credentials
      pushed, smoke check passed
- [ ] `fleet health` says all 5 nodes OK
- [ ] The hello-fleet job finished on all five and `fleet pull` downloaded it
