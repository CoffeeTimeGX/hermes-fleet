# Updates

The fleet has five parts that update separately. None of them updates by itself in a
way that could surprise you, except the security updates of the VPSs' operating
system.

| Part | How it updates |
| --- | --- |
| The fleet code (this repository) | `git pull` on your PC, then `fleet sync` for the VPSs |
| Claude Code on the VPSs | `fleet provider install claude all` when you choose |
| Hermes on your PC | `hermes update` when you choose |
| Ubuntu on the VPSs | Security updates install by themselves; everything else with a bootstrap re-run |
| Tailscale | By itself on your PC; on the VPSs once you turn it on (below) |

## The fleet code

On your PC, in the repository folder:

```
git pull
fleet sync
```

`git pull` updates everything on your PC at once: the `fleet` command, Hermes' skills
and its `SOUL.md`. `fleet sync` copies the new `vps/` folder (the worker, the provider
scripts and the job templates) to every VPS and restarts each worker.

Running jobs are not interrupted. Each job runs in its own process session, and a
restarted worker finds the running jobs again.

Then check the result with `fleet status`. The new worker version is in
`fleet status --json` (`worker_version`).

Two things are not covered by `fleet sync`:

- **Hermes' copy of `SOUL.md`** and the settings `fleet init` manages. Run `fleet init`
  again when the release notes ask for it. It keeps your inventory, secrets and SSH key,
  and backs up Hermes' `config.yaml` before it changes anything.
- **The system files on a VPS** (the systemd services, `/etc/fleet/worker.env`, the
  firewall and SSH settings). When those change, re-run the bootstrap over Tailscale:
  `fleet bootstrap vps1 --skip-upgrade`. It is safe to repeat, keeps public SSH closed
  on a locked-down VPS, and does not stop running jobs.

## Claude Code on the VPSs

Claude Code's own auto-updater is off on the VPSs, so all five stay on the same version
until you decide:

```
fleet provider install claude all                      # the newest stable release
fleet provider install claude all --version latest     # the newest release
fleet provider install claude all --version 2.1.300    # one exact version
fleet provider check claude all --smoke
```

The install first runs `fleet sync`, then Anthropic's installer on each VPS. A session
that is already running keeps the version it started with; the next job uses the new
one. Run the `--smoke` check afterwards: it starts one tiny session on each VPS.

If a new version misbehaves, install the previous version number the same way.

## Hermes on your PC

```
hermes update
hermes gateway restart
```

`hermes update` installs the newest stable Hermes release. Restart the gateway so the
scheduled checks and Telegram use it. Then ask Hermes *"how is the fleet?"* to check that
its skills still work. If something in the fleet setup broke, run `fleet doctor`, then
`fleet init`.

## Ubuntu on the VPSs

- **Security updates** install automatically every day. When one needs a reboot (a new
  kernel, for example), `fleet health` tells you. Reboot when no job runs:

    ```
    fleet reboot vps1
    ```

    It refuses while jobs are running. With `--force`, the running jobs are stopped and
    start again after the reboot (once, by default). A VPS is usually back in about a
    minute.

- **Everything else** updates when you re-run the bootstrap without `--skip-upgrade`,
  for example every few months:

    ```
    fleet bootstrap vps1
    ```

## Tailscale

On your PC, Tailscale updates like any other app; on Windows and macOS it can update
itself (see its settings). On the VPSs, turn on Tailscale's automatic updates once:

```
fleet exec all --root -- tailscale set --auto-update
```

Tailscale then updates itself and picks a quiet moment to do it. The jobs do not depend
on Tailscale, so an update does not touch them; only your connection to that VPS pauses
for a moment.

## Versions

| What | Where to see it |
| --- | --- |
| The `fleet` command | `fleet --version` |
| The worker on each VPS | `fleet status --json`, field `worker_version` |
| Claude Code on each VPS | `fleet provider check claude all` |
| Hermes | `hermes --version` |
