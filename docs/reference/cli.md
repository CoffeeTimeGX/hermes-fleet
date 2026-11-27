# Command reference

`fleet` is the one command that runs the fleet from your PC. Hermes uses exactly these
commands; you can use them by hand in any terminal. It is a single Python file,
`home/bin/fleet`, that needs Python 3.9 or newer and nothing else, and works the same on
Windows, Linux and macOS.

```
fleet --help              # every command
fleet dispatch --help     # one command's options
fleet --version
```

## Targets

Many commands take `TARGETS`, the VPSs to act on:

| You write | It means |
| --- | --- |
| `all`, or nothing where `TARGETS` is optional | every VPS in your inventory with `enabled = true` |
| `vps3` | one VPS, even a disabled one |
| `vps1,vps3` | a list, without spaces |

Commands that act on several VPSs do it on all of them at the same time, and report
each one separately: one unreachable VPS never stops the others.

## Global options

| Option | Meaning |
| --- | --- |
| `--config PATH` | Use another inventory file. Default: `~/.config/fleet/fleet.ini`, or `$FLEET_CONFIG`. Put it before the command: `fleet --config other.ini status`. |
| `--version` | Print the version of `fleet`. |

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Something failed, or one of the VPSs did. The message says what. |
| `2` | `fleet health` found problems, or `fleet check` found problems in a video. |
| `130` | You pressed Ctrl+C. |

`fleet exec` returns the exit code of the remote command (the first non-zero one when it
ran on several VPSs).

## Everyday commands

### fleet status

```
fleet status [TARGETS] [--json]
```

One line per VPS: the worker service, the queue, disk, load and providers. See
[Everyday use](../operations/everyday.md#check-the-fleet) for the columns. With `--json`,
the full status each worker reports, as a list.

### fleet health

```
fleet health [--quiet | --changes-only] [--remind-hours H] [--min-disk-pct P] [--max-backlog N]
```

Checks every enabled VPS and prints only the problems, each with its fix. Exits with 2
when there are problems.

| Option | Meaning |
| --- | --- |
| `--quiet` | Print nothing when everything is fine. |
| `--changes-only` | Print only new and resolved problems, and a reminder of the open ones every `--remind-hours`. Always exits with 0. The scheduled health check uses this; it keeps its memory in `~/.config/fleet/state/health.json`. |
| `--remind-hours H` | How often to remind about open problems with `--changes-only`. Default 6. |
| `--min-disk-pct P` | Report a disk with less than P% free. Default 15. |
| `--max-backlog N` | Report a queue with more than N waiting jobs. Default 25. |

The problems it knows are listed in [Scheduled checks](../operations/scheduled-checks.md#the-health-check).

### fleet dispatch

```
fleet dispatch JOB.json [JOB.json ...] [--to TARGET] [--channel C] [--provider P] [--dry-run] [--json]
fleet dispatch --prompt "TEXT" [--channel C] [--to TARGET]
```

Checks each job and queues it. Wildcards such as `jobs/*.json` work in every shell.

| Option | Meaning |
| --- | --- |
| `--to auto` | The default: the VPS that makes videos for the job's channel (`channels` in your inventory), or the least busy of them when several do. The job waits there when that VPS is busy, paused or at its usage limit. A channel that no VPS names goes to the least busy ready VPS with `channels = all`. |
| `--to all` | One copy on every reachable VPS that offers the job's provider. Each copy's id ends in the VPS's name. |
| `--to vps2` or `--to vps2,vps4` | The least busy of these VPSs, whatever channels they make (you get a note when the VPS does not make the job's channel). When none of them is ready, the job is queued anyway, with a warning. |
| `--channel C`, `--provider P` | Replace that field in every job of this command. |
| `--prompt "TEXT"` | Make a job from this text instead of a file. |
| `--dry-run` | Print each job as it would be queued, without contacting any VPS. |
| `--json` | Print the queued jobs as JSON: node, id and channel. |

Work never moves to another VPS by itself: only `--to`, `fleet retry --to` and
`fleet handover` move it. A job is refused, with the reason, when no VPS makes its
channel, when its channel's VPS is unreachable, or when the job's provider is not
installed or has no credentials there, because the job would only fail. See
[Job format](../operations/job-format.md) for the file.

### fleet jobs

```
fleet jobs [TARGETS] [--state inbox|outgoing|running|done|failed|moved] [--json]
```

Every job on the VPSs, with its state, times (UTC) and the reason a job failed or waits.
`outgoing` is a job that `fleet handover` is moving to another VPS, and `moved` is what a
job made on a VPS before it was handed over (it waits for the pull).
`(pulled)` marks jobs your PC already has. `--json` adds every field, including
`duration_s`, `exit_code`, `attempts`, `limit_waits` and the last lines of a failed job's
log (`log_tail`).

### fleet logs

```
fleet logs NODE JOB_ID [-f]
```

The last 200 lines of a job's provider log. With `-f`, keeps following it until you press
Ctrl+C. A job that is still waiting in the queue has no log yet.

### fleet cancel

```
fleet cancel NODE JOB_ID
```

Removes a waiting job from the queue (also one that is `outgoing`), or stops a running
one. Either way it is filed as `failed` with the reason `cancelled`.

### fleet retry

```
fleet retry NODE JOB_ID [--to TARGET]
```

Queues a fresh copy of a finished or failed job, from the `job.json` in its workspace.
The copy's id ends in `-r1` (`-r2` for a retry of a retry), and it records `retry_of`.
It goes to the same VPS unless `--to` says otherwise (`--to auto` sends it to the VPS
that makes its channel). The workspace must still be on the VPS: it is deleted 7 days
after the job was pulled.

### fleet handover

```
fleet handover FROM TO [JOB_ID ...] [--dry-run]
```

Moves queued jobs from one VPS to another. Use it only when you want another VPS to make
them: nothing else moves work between VPSs. Without job ids, it moves every job that
waits in FROM's queue. `--dry-run` shows what would move, and moves nothing.

- The jobs keep their ids and wait in TO's queue. When TO already has a job with the
  same id, the moved one gets `-h1` at the end (then `-h2`, and so on).
- Running jobs stay on FROM. To move one anyway: `fleet cancel FROM JOB_ID`, then
  `fleet retry FROM JOB_ID --to TO`.
- A job that had already started on FROM, for example one that waits for a usage limit,
  starts over on TO. What it made on FROM is filed as `moved` and comes home with the
  next `fleet pull`, marked `[MOVED]`.
- Both VPSs must answer. A job stays on FROM when TO does not offer its provider, or when
  that provider is not installed or has no credentials on TO.
- New jobs for the channel still go to the VPS that your inventory names for it. To give
  a channel to another VPS for good, change `channels` (see
  [Configuration](config.md#fleetini)).
- If a move breaks halfway, for example when the connection drops, the job shows as
  `outgoing` on FROM and does not run there. Run the same `fleet handover` again: it
  finishes the move and never makes a second copy. `fleet health` reports a job that
  stays `outgoing` for more than 10 minutes.

### fleet pull

```
fleet pull [TARGETS] [--quiet]
```

Downloads every finished job that is not on your PC yet into the results folder, marks
it as pulled on the VPS, adds a line to `index.jsonl` and prints each job's summary. See
[Results](../operations/results.md). With `--quiet`, it prints nothing when there is
nothing new and says nothing about unreachable VPSs (the health check reports those).

### fleet pause, fleet resume

```
fleet pause TARGETS [--reason TEXT]
fleet resume TARGETS
```

`pause` stops a VPS from starting new jobs; running jobs finish normally. `resume` starts
the queue again, and also ends a usage-limit wait early. It does not override the VPS's
[work schedule](../operations/schedule.md). Both need `TARGETS`; use `all` for every VPS.

### fleet schedule

```
fleet schedule [show] [TARGETS] [--json]
fleet schedule set TARGETS [24/7] [--hours H] [--days D] [--off DATES] [--cycle WORK/REST]
                   [--gap G] [--random N/day [--min-gap G]] [--cap N] [--tz ZONE]
fleet schedule open TARGETS [--for LENGTH]
fleet schedule close TARGETS
```

The hours each VPS works. It trumps everything: no job starts outside it, whoever
queued it, and running jobs always finish. Without a schedule a VPS works 24/7.

| Option | Example | Off |
| --- | --- | --- |
| `--hours` | `08:00-12:00,14:00-23:00`, `22:00-07:00` | `all` |
| `--days` | `mon-fri`, `weekends`, `mon,wed,fri` | `all` |
| `--off` | `2026-12-24..2026-12-26,2027-01-01`, `today`, `tomorrow` | `none` |
| `--cycle` | `3h/1h`: 3 hours of work, 1 hour of rest | `off` |
| `--gap` | `45m`: a rest after each video | `0` |
| `--random` | `4/day`: 4 random start times a day; `--min-gap 1h` spaces them | `off` |
| `--cap` | `3`: at most 3 jobs a day | `0` |
| `--tz` | `Europe/Paris`, `UTC`, `+01:00` | |

Each option changes only itself. `24/7` clears everything first. `open` gives extra work
time now (one hour by default, at most 7 days), whatever the schedule says; `close` ends
it. See [Work schedule](../operations/schedule.md).

### fleet check

```
fleet check NODE JOB_ID [--json]
```

Looks at a finished job's video again and prints the verdict. Exits with 2 when it finds
problems. See [Video check](../operations/video-check.md).

### fleet report

```
fleet report [--hours HOURS] [--json]
```

The daily report: what each VPS made, the videos with problems, the failed jobs, the
week plan, what was published, and what needs you. `--hours` looks further back than
the last 24 hours. Hermes sends it every morning at 9.

### fleet plan

```
fleet plan show [--week this|next|all] [--status STATUS] [--channel C] [--json]
fleet plan slots [--week this|next] [--channel C] [--json]
fleet plan add --channel C --day YYYY-MM-DD --title T [--time HH:MM] [--brief B]
fleet plan import FILE.json
fleet plan approve NUMBERS
fleet plan reject NUMBERS
fleet plan edit NUMBER [--title T] [--brief B] [--day YYYY-MM-DD] [--time HH:MM] [--channel C]
fleet plan remove NUMBERS
fleet plan run [--dry-run] [--quiet]
```

The week plan: topics that wait for your yes, then are queued on their channel's VPS at
their time. `NUMBERS` are plan numbers like `12`, `12,14`, `12-15` or `all` (every
draft). `import` takes a JSON list of `{"channel", "day", "title", "brief"}`, or `-` to
read it from the keyboard or a pipe. `run` queues what is due; Hermes runs it every
hour. See [Week plan](../operations/week-plan.md).

### fleet ideas

```
fleet ideas [--json]
fleet ideas add TITLE [--note TEXT] [--at NUMBER] [--status STATUS]
fleet ideas edit NUMBER [--title T] [--note TEXT] [--status idea|next|building|built]
fleet ideas move NUMBER --to NUMBER
fleet ideas remove NUMBERS
```

Your ideas list: notes and features to build into the fleet later, best first. The
numbers are the places in the list, so look with `fleet ideas` before you change one.
`--at 1` and `--to 1` put an idea first. An idea marked `built` moves to the end of the
list. `NUMBERS` are one or more numbers, like `3` or `3,5`. Until you change it, the list
holds the starter ideas, with the trend looker first. The studio shows it in the ideas
office on the pixel lot, and Hermes adds what you tell it on Telegram. The list is
`ideas.json`, next to `fleet.ini`.

### fleet publish

```
fleet publish NODE JOB_ID --to youtube,tiktok,instagram [--at "YYYY-MM-DD HH:MM"] [--now]
              [--video-url URL] [--channel C] [--anyway] [--dry-run] [--json]
fleet publish --login youtube|tiktok|instagram --channel C [--made-for-kids yes|no]
              [--no-ai-label] [--ig-user-id ID] [--port PORT]
fleet publish --accounts
```

Sends a pulled video to YouTube as a private video, to the TikTok inbox, or to Instagram
as a public Reel (that one needs `--now`). `--at` makes the YouTube video go public by
itself at that time. `--login` signs a channel in, once per platform. See
[Publishing](../operations/publishing.md).

### fleet studio

```
fleet studio [--tailnet] [--port PORT] [--every SECONDS] [--no-browser] [--json]
```

Opens a page in your browser that shows every VPS at work, like a film lot seen from
above: what each Claude session is doing now, what waits and what finished today. Its
**Pixel lot** view (`/pixel.html`) draws the same fleet as a pixel-art studio, where you
click anyone to see the real values they stand for. Both play back the last 24 hours,
and play the videos you have collected with `fleet pull`. It looks at the VPSs every 20
seconds, only watches, and runs until you press Ctrl+C. See
[The studio](../operations/studio.md).

| Option | Meaning |
| --- | --- |
| `--tailnet` | Open it on your PC's Tailscale address instead of `127.0.0.1`, so that your phone and your other devices can watch too. |
| `--port PORT` | The port on your PC. Default 8740. |
| `--every SECONDS` | How often it looks at the VPSs. Default 20, at least 5. |
| `--no-browser` | Do not open the browser. |
| `--json` | Look once, print what it saw as JSON, and exit. |

## Setup and maintenance

### fleet init

```
fleet init [--no-hermes]
```

Sets up your PC; the installers run it. It never overwrites a file you already have:

- creates the inventory (`~/.config/fleet/fleet.ini`) from `home/fleet.ini.example`,
- creates a Claude secrets file for each VPS and the Tailscale secrets file, and makes
  the secrets folder private to your user,
- creates the fleet SSH key (`~/.ssh/fleet_ed25519`, no passphrase) and an SSH config,
  so `ssh vps1` works,
- installs the `fleet` command in `~/.local/bin`,
- sets up Hermes: creates the Hermes profile `director` if it is missing, then copies
  `SOUL.md` into it, writes the two scheduled-check scripts, and applies the director's
  settings. See [Configuration](config.md#hermes).

It leaves the director's model alone (choose it with `hermes -p director model`) and
prints the one it uses. `--no-hermes` skips the Hermes part. Running `fleet init` again
is safe.

### fleet doctor

```
fleet doctor
```

Checks your PC: Python, the SSH client, Git (and Git Bash on Windows), Hermes and its
`director` profile, the director's working folder and model, Tailscale, `~/.local/bin`
on your PATH, the inventory, the channel of each VPS, the SSH key, the secrets files and
whether each VPS name resolves. Exits with 1 when a required check fails; warnings do
not fail it.

### fleet hermes-cron

```
fleet hermes-cron [--deliver TARGET]
```

Creates the five scheduled Hermes jobs in the `director` profile, unless they already
exist (`hermes -p director cron list` shows them). `--deliver` says where their messages
go; the default is `telegram`. See [Scheduled checks](../operations/scheduled-checks.md).

### fleet list

```
fleet list
```

Prints your inventory: each VPS's host, public IP, Hostinger account, providers,
sessions, channels and whether it is enabled. It does not contact the VPSs.

### fleet ping

```
fleet ping [TARGETS]
```

Checks that each VPS answers over SSH, and how fast: `vps1     ok 84 ms`. Exits with 1
when any VPS does not answer, and prints its SSH error.

### fleet ssh-config

```
fleet ssh-config
```

Prints the SSH settings for every VPS, as `fleet init` wrote them to
`~/.ssh/config.d/fleet`.

### fleet bootstrap

```
fleet bootstrap NODE [--public] [--skip-upgrade] [--tz ZONE]
```

Sets up a VPS as root: uploads the repository's `vps/` folder and runs `bootstrap.sh`.
See [Provision a VPS](../vps/provisioning.md#2-bootstrap) for everything it does. It
passes the VPS's name, your fleet public key, the `sessions` value from your inventory
and the Tailscale auth key from your secrets.

| Option | Meaning |
| --- | --- |
| `--public` | Connect to the VPS's `public_ip`. Only for the first run, before it is on Tailscale. |
| `--skip-upgrade` | Skip the full OS upgrade, for quick re-runs. |
| `--tz ZONE` | The VPS's timezone, for example `Europe/Paris`. Default `UTC`, or `$FLEET_TZ`. |

Safe to run again on a working VPS: running jobs continue, and a locked-down VPS stays
locked down.

### fleet lockdown

```
fleet lockdown NODE [--undo]
```

Closes public SSH on a VPS, so it answers only over Tailscale. `--undo` opens it again.
See [Close public SSH](../vps/lockdown.md).

### fleet provider

```
fleet provider install NAME [TARGETS] [--version VERSION]
fleet provider check NAME [TARGETS] [--smoke]
```

`install` syncs the fleet code to the VPSs, then runs the provider's `install.sh` as the
`fleet` user. For Claude, `--version` is `stable` (the default), `latest` or an exact
version such as `2.1.300`. `check` runs the provider's health check; `--smoke` also runs
one tiny real session. `TARGETS` defaults to `all`.

### fleet secrets

```
fleet secrets push NAME [TARGETS]
```

Copies a provider's credentials to the VPSs. For each VPS it reads
`~/.config/fleet/secrets/<vps>/<NAME>.env`, or `~/.config/fleet/secrets/<NAME>.env` when
there is no file for that VPS. Empty values are left out. On the VPS, the values go to
`~/.config/fleet/providers/<NAME>.env`, readable only by the `fleet` user. It prints the
names of the values, never the values. On Linux and macOS it refuses a secrets file that
other users can read. `TARGETS` defaults to `all`.

### fleet sync

```
fleet sync [TARGETS]
```

Copies the repository's `vps/` folder (worker, providers, templates) to the VPSs and
restarts each worker. Running jobs continue. Prints the worker version each VPS now runs.

### fleet restart

```
fleet restart [TARGETS]
```

Restarts the worker service. Running jobs continue.

### fleet reboot

```
fleet reboot NODE [--force]
```

Reboots a VPS. It refuses while jobs are running; with `--force`, it reboots anyway, and
the running jobs start again afterwards (once, by default).

### fleet exec

```
fleet exec TARGETS [--root] [--timeout SECONDS] -- COMMAND...
```

Runs a shell command on the VPSs, as the `fleet` user or, with `--root`, as root.
Everything after `--` is the command. Quote it when it has pipes or redirections:
`fleet exec vps1 -- "df -h | tail -n 1"`. Each VPS's output comes after a line such as
`--- vps1 (exit 0)`. The default timeout is 600 seconds.

### fleet forget-host

```
fleet forget-host NODE
```

Removes the VPS's old SSH host keys from your PC (for its name, Tailscale host and public
IP). Use it after a rebuild, when SSH warns that the host identification has changed.

## Environment variables

| Variable | Meaning |
| --- | --- |
| `FLEET_CONFIG` | The inventory file, instead of `~/.config/fleet/fleet.ini`. |
| `FLEET_STATE_DIR` | Where `fleet health --changes-only` keeps its memory. Default `~/.config/fleet/state`. |
| `FLEET_TZ` | The default for `fleet bootstrap --tz`. |
| `FLEET_PULL_METHOD` | `tar` makes `fleet pull` use a compressed archive over SSH instead of rsync. |
| `HERMES_HOME` | Hermes' main folder (its default profile), if it is not in the default place. |
| `FLEET_TRANSPORT` | `local` runs every command on this computer instead of over SSH. For the tests only. |
