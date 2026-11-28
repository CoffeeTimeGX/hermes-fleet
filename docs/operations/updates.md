# Updates

The fleet has six parts that update separately. None of them updates by itself in a
way that could surprise you, except the security updates of the VPSs' operating
system.

| Part | How it updates |
| --- | --- |
| The fleet code (this repository) | `git pull` on your PC, then `fleet sync` for the VPSs |
| Claude Code on the VPSs | `fleet provider install claude all` when you choose |
| Skills on the VPSs | `fleet skills install all` when the list changes ([Skills on the VPSs](../providers/skills.md)) |
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

- **The director's copy of `SOUL.md`** and the settings `fleet init` manages. Run
  `fleet init` again when the release notes ask for it. It keeps your inventory, secrets
  and SSH key, and backs up the director's `config.yaml` before it changes anything.
- **The system files on a VPS** (the systemd services, `/etc/fleet/worker.env`, the
  firewall and SSH settings). When those change, re-run the bootstrap over Tailscale:
  `fleet bootstrap vps1 --skip-upgrade`. It is safe to repeat, keeps public SSH closed
  on a locked-down VPS, and does not stop running jobs.

### From version 1.10 to 1.11

Version 1.11 gives every VPS the same Claude Code skills, from a list in the repository.
The first is [Lumina SFX](../providers/skills.md#lumina-sfx): an offline library of sound
effects that the jobs can search, layer and export as WAV files, free for monetized
videos. After `git pull`:

```powershell
fleet skills install all
```

It syncs the fleet code to the VPSs, then installs Lumina SFX on each VPS, with the
Node.js it needs, for the `fleet` user only (a few minutes the first time). Running jobs
are not interrupted. Check the result with `fleet skills`.

The pixel lot plays Lumina SFX recordings too when you turn its sound on: the clap of the
slate, a chime for a finished video, birds, crickets, rain, wind and the town. They come
with `git pull`; restart `fleet studio` if it is running.

### From version 1.9 to 1.10

Version 1.10 lets a trend take the rest of the day: answer *shift 3* to a pitch, and
today's other videos turn to its subject, each on its usual VPS and at its usual time.
On the pixel lot, the zeppelin drops flyers on the stages that would change. See
[Shift the day](trends.md#shift-the-day). After `git pull`:

```powershell
fleet sync
```

It keeps the VPSs on the same version number as your PC; nothing else changes on them.
Hermes' skill comes with `git pull`, and so does the new message of its `fleet-trends`
job, so there is no need to run `fleet hermes-cron` or `fleet init` again.

### From version 1.8 to 1.9

Version 1.9 adds the [trend looker](trends.md), the zeppelin over the pixel lot: three
times a day it looks at what is rising on YouTube in each channel's niche, and Hermes
pitches you a video on it. After `git pull`:

```powershell
fleet sync
fleet hermes-cron
fleet init
fleet trends key
```

- `fleet sync` keeps the VPSs on the same version number as your PC; nothing else
  changes on them.
- `fleet hermes-cron` adds the `fleet-trends` job and leaves your other jobs.
- `fleet init` mends your secrets folder on Windows. An earlier version could leave the
  files in it unreadable, even for you. It keeps your files as they are.
- `fleet trends key` saves your YouTube Data API key. Make the key first:
  [Set it up](trends.md#set-it-up).
- If you changed your ideas list, the trend looker is still on it as an idea. Mark it
  built: `fleet ideas`, then `fleet ideas edit <its number> --status built`.

### From version 1.7 to 1.8

Version 1.8 adds the ideas list (`fleet ideas`) and the pitch room on the pixel lot, where
Nova reads it out.
After `git pull`:

```powershell
fleet sync
```

It keeps the VPSs on the same version number as your PC; nothing else changes on them.
Hermes' skill comes with `git pull`, so Hermes can add your ideas from Telegram.

### From version 1.6 to 1.7

Version 1.7 adds the [video check](video-check.md), the [week plan](week-plan.md),
[publishing](publishing.md) and the [work schedule](schedule.md). After `git pull`:

```powershell
fleet sync
fleet hermes-cron
fleet init
```

- `fleet sync` brings the video check and the schedule to every VPS.
- `fleet hermes-cron` adds the hourly week plan job and Sunday's planning, and replaces
  the old `fleet-daily-report` with `fleet-report`, which costs no model use.
- `fleet init` gives Hermes the new version of its instructions.
- Once per VPS, for schedules in a named time zone such as `Europe/Paris`:
  `fleet bootstrap vps1 --skip-upgrade`. It installs the time zone data if the VPS lacks
  it. `fleet schedule set` tells you when a VPS needs it.

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
scheduled checks and Telegram use it. Then ask the director *"how is the fleet?"* to
check that its skills still work. If something in the fleet setup broke, run
`fleet doctor`, then `fleet init`.

## Upgrading to the director profile

Fleet setups from before version 1.3.0 used Hermes' default profile. Since 1.3.0 the
fleet runs from its own profile, `director`, which `fleet init` creates. When an older
setup is still there, `fleet init` says so. These steps finish the move:

1. Update, and let `fleet init` set up the director:

    ```
    git pull
    fleet init
    ```

2. Choose the director's model. Each profile has its own settings and keys, so the
   wizard asks again:

    ```
    hermes -p director model
    ```

3. Move the Telegram bot to the director, because a bot token works in one profile
   only. Open the default profile's `.env` (`%LOCALAPPDATA%\hermes\.env` on Windows,
   `~/.hermes/.env` on Linux and macOS) and delete its `TELEGRAM_` lines. Then give the
   bot to the director and restart the gateway:

    ```
    hermes -p director gateway setup
    hermes gateway restart
    ```

    Send `/sethome` to the bot again, so that the scheduled reports find your chat.

4. Move the scheduled checks: remove the old ones from the default profile, then create
   them for the director.

    ```
    hermes cron remove fleet-health
    hermes cron remove fleet-pull
    hermes cron remove fleet-daily-report
    fleet hermes-cron
    ```

5. Delete `fleet_health.py` and `fleet_pull.py` from the default profile's `scripts`
   folder (`%LOCALAPPDATA%\hermes\scripts` on Windows, `~/.hermes/scripts` on Linux and
   macOS). After that, `fleet init` no longer sends you here.

Check with `fleet doctor`: it shows the director profile and its model. Your default
Hermes keeps the fleet's `SOUL.md` and settings from before, and an older `fleet init`
may have set it to a Claude model. If you use it for other things, `hermes model`
changes its model, and the backups `config.yaml.bak-<date>` and `SOUL.md.bak-<date>` in
its folder hold what it had before.

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
| The skills on each VPS | `fleet skills` |
| Hermes | `hermes --version` |
