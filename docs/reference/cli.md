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
| `2` | `fleet health` found problems. |
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
| `--to auto` | The default: the least busy VPS that can start the job now. If every VPS waits for a usage limit, the one whose limit ends first. |
| `--to all` | One copy on every reachable VPS that offers the job's provider. Each copy's id ends in the VPS's name. |
| `--to vps2` or `--to vps2,vps4` | The least busy of these VPSs. When none of them is ready, the job is queued anyway, with a warning. |
| `--channel C`, `--provider P` | Replace that field in every job of this command. |
| `--prompt "TEXT"` | Make a job from this text instead of a file. |
| `--dry-run` | Print each job as it would be queued, without contacting any VPS. |
| `--json` | Print the queued jobs as JSON: node, id and channel. |

A VPS can take a job when it is reachable, its worker is active, it is not paused, low
on disk or waiting for a usage limit, and the job's provider is installed and working
on it. See [Job format](../operations/job-format.md) for the file.

### fleet jobs

```
fleet jobs [TARGETS] [--state inbox|running|done|failed] [--json]
```

Every job on the VPSs, with its state, times (UTC) and the reason a job failed or waits.
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

Removes a waiting job from the queue, or stops a running one. Either way it is filed as
`failed` with the reason `cancelled`.

### fleet retry

```
fleet retry NODE JOB_ID [--to TARGET]
```

Queues a fresh copy of a finished or failed job, from the `job.json` in its workspace.
The copy's id ends in `-r1` (`-r2` for a retry of a retry), and it records `retry_of`.
It goes to the same VPS unless `--to` says otherwise (`--to auto` lets the least busy
one take it). The workspace must still be on the VPS: it is deleted 7 days after the job
was pulled.

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
the queue again, and also ends a usage-limit wait early. Both need `TARGETS`; use `all`
for every VPS.

## Setup and maintenance

### fleet init

```
fleet init [--keep-model] [--no-hermes]
```

Sets up your PC; the installers run it. It never overwrites a file you already have:

- creates the inventory (`~/.config/fleet/fleet.ini`) from `home/fleet.ini.example`,
- creates a Claude secrets file for each VPS and the Tailscale secrets file, and makes
  the secrets folder private to your user,
- creates the fleet SSH key (`~/.ssh/fleet_ed25519`, no passphrase) and an SSH config,
  so `ssh vps1` works,
- installs the `fleet` command in `~/.local/bin`,
- sets up Hermes: copies `SOUL.md`, writes the two scheduled-check scripts, and applies
  the director's settings. See [Configuration](config.md#hermes).

`--keep-model` leaves Hermes' model setting alone. `--no-hermes` skips the Hermes part.
Running `fleet init` again is safe.

### fleet doctor

```
fleet doctor
```

Checks your PC: Python, the SSH client, Git (and Git Bash on Windows), Hermes, Tailscale,
`~/.local/bin` on your PATH, the inventory, the SSH key, the secrets files, whether each
VPS name resolves, and Hermes' working folder. Exits with 1 when a required check fails;
warnings do not fail it.

### fleet hermes-cron

```
fleet hermes-cron [--deliver TARGET]
```

Creates the three scheduled Hermes jobs, unless they already exist. `--deliver` says
where their messages go; the default is `telegram`. See
[Scheduled checks](../operations/scheduled-checks.md).

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
| `HERMES_HOME` | Hermes' folder, if it is not in the default place. |
| `FLEET_TRANSPORT` | `local` runs every command on this computer instead of over SSH. For the tests only. |
