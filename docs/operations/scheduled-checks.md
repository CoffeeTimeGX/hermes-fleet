# Scheduled checks

Hermes watches the fleet for you with three scheduled jobs. `fleet hermes-cron` creates
them once, during the home setup:

```
fleet hermes-cron
```

```
+ fleet-health
+ fleet-pull
+ fleet-daily-report
Cron runs inside the Hermes gateway: keep it running (hermes gateway status).
```

Running it again changes nothing: jobs that already exist are left alone.

| Job | When | What it does | Costs |
| --- | --- | --- | --- |
| `fleet-health` | every 10 minutes | Runs `fleet health --changes-only` and messages you when a problem appears or goes away. | nothing |
| `fleet-pull` | every 30 minutes | Runs `fleet pull --quiet` and messages you the summary of each job it downloaded. | nothing |
| `fleet-daily-report` | every day at 9 am | Hermes reads `fleet status` and `fleet jobs` and writes you a short report. | one short Hermes conversation |

The first two are plain scripts: Hermes runs them without its model and sends whatever
they print. When they print nothing, you get no message. That is how the fleet stays
quiet when all is well.

## The health check

Every 10 minutes, the health check asks each VPS for its status and compares the
problems with the previous check. It messages you:

- when a problem is **new**,
- every **6 hours** while a problem is still open, as a reminder,
- when a problem is **resolved**.

```
Fleet health: 2 open problem(s)
NEW  vps4: unreachable (ssh: connect to host vps4 port 22: Connection timed out)
STILL vps2: low disk, 2.6 GB free (3%), new jobs are on hold; run fleet pull, then see the disk-full runbook
```

```
Fleet health: resolved
OK   vps4: unreachable (ssh: connect to host vps4 port 22: Connection timed out)
```

It looks for these problems:

| Problem | Fix |
| --- | --- |
| A VPS is unreachable | [VPS unreachable](../runbooks/vps-unreachable.md) |
| The worker service is not active, or its loop stopped (no heartbeat for 3 minutes) | `fleet restart <vps>` |
| A VPS is paused | `fleet resume <vps>` when you are ready |
| Free disk under 15%, or under 3 GB (new jobs then wait) | [Disk full](../runbooks/disk-full.md) |
| Claude is not installed, or not working (no credentials, failed check) | [Provision a VPS](../vps/provisioning.md), steps 5 to 7 |
| A subscription token is 330 days old (it expires after a year) | [Rotate credentials](../runbooks/rotate-credentials.md) |
| More than 25 jobs wait in one queue | Spread the work, or check why the VPS is slow |
| Security updates need a reboot | `fleet reboot <vps>` when no job runs |
| A usage-limit wait longer than 6 hours (a weekly limit) | Nothing to do: [Usage limits](usage-limits.md) |

The check remembers what it reported in `~/.config/fleet/state/health.json` on your PC.

## The pull

Every 30 minutes, the pull downloads every finished job that is not on your PC yet and
sends you one message:

```
Pulled 1 finished job(s) into C:\Users\you\fleet-results:
[done] vps2/20261118-101145-space-facts-a81kd  channel: Space Facts
    C:\Users\you\fleet-results\vps2\20261118-101145-space-facts-a81kd
    Made a 58-second vertical short about Saturn's rings. Files in ./output/: video.mp4, ...
```

When there is nothing new, it stays silent. It also stays silent about a VPS it could
not reach, because the health check already reports that.

## The daily report

At 9 am, Hermes runs `fleet status` and `fleet jobs` with its `fleet-ops` skill and
sends you a report of at most 12 lines: each VPS's health, the jobs that finished and
failed in the last 24 hours, what is still queued or running, and anything you need to
do. This is the only one of the three that uses Hermes' model, and so its API key.

## Where the messages go

`fleet hermes-cron` delivers to Telegram, into the chat where you sent `/sethome`
(see [Telegram](../home/telegram.md)). To deliver somewhere else Hermes supports, give
the target when you create the jobs, for example `fleet hermes-cron --deliver discord`.
With `--deliver local`, Hermes only saves the messages in its `cron/output/` folder.

## Times and timezone

Hermes reads *"every day at 9am"* in the timezone of its settings. If the report comes
at the wrong hour, set your timezone in Hermes' settings (`timezone:` in its
`config.yaml`, which `hermes config edit` opens), or give the report its own timezone:

```
hermes cron edit fleet-daily-report --timezone Europe/London
```

Use your own zone's name from the
[tz database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones). The
10-minute and 30-minute jobs do not depend on the timezone.

## They run only while the gateway runs

The Hermes gateway runs the schedule. While your PC is off, asleep or logged out, no
check runs, but the VPSs keep working. When the gateway is back, the next pull collects
everything and the next health check reports what is still wrong. See
[Keep it running](../home/always-on.md).

## Manage the jobs

```
hermes cron list                          # the jobs and their next run
hermes cron run fleet-daily-report        # run one within the next minute, as an extra
hermes cron pause fleet-health            # stop one for a while
hermes cron resume fleet-health
hermes cron remove fleet-daily-report     # delete one (fleet hermes-cron creates it again)
```

The two script jobs run small Python files that `fleet init` wrote into Hermes'
`scripts/` folder: `fleet_health.py` and `fleet_pull.py`. They point at your copy of the
repository and your inventory. To change a threshold of the health check, edit the
argument list in `fleet_health.py`, for example
`["health", "--changes-only", "--min-disk-pct", "10"]`. The options are
`--min-disk-pct` (default 15), `--max-backlog` (default 25) and `--remind-hours`
(default 6); see the [command reference](../reference/cli.md#fleet-health).
`fleet init` writes both files again each time it runs, so repeat the edit after it.
