# Scheduled checks

Hermes watches the fleet for you with five scheduled jobs of its `director` profile.
`fleet hermes-cron` creates them once, during the home setup:

```
fleet hermes-cron
```

```
+ fleet-health
+ fleet-pull
+ fleet-report
+ fleet-plan
+ fleet-week-plan
These jobs belong to the 'director' profile (hermes -p director cron list). They run inside
the Hermes gateway: keep it running (hermes gateway status). Their times are in the profile's timezone.
```

Running it again only adds the jobs that are missing. It also replaces the
`fleet-daily-report` job of older versions with `fleet-report`.

| Job | When | What it does | Costs |
| --- | --- | --- | --- |
| `fleet-health` | every 10 minutes | Runs `fleet health --changes-only` and messages you when a problem appears or goes away. | nothing |
| `fleet-pull` | every 30 minutes | Runs `fleet pull --quiet` and messages you the summary of each job it downloaded. | nothing |
| `fleet-report` | every day at 9 am | Runs `fleet report` and sends you the daily report. | nothing |
| `fleet-plan` | every hour | Runs `fleet plan run --quiet`: queues the approved topics whose time has come. | nothing |
| `fleet-week-plan` | Sundays at 10 am | Hermes plans next week's topics and sends them to you to approve. See [Week plan](week-plan.md). | one Hermes conversation |
| `fleet-trends` | every day at 8 am, 1 pm and 6 pm | Runs `fleet trends look`. Only when a video rises fast in a channel's niche, Hermes wakes and pitches you a video on it. See [Trend looker](trends.md). | YouTube quota; a Hermes conversation only when something rises |

The first four are plain scripts: Hermes runs them without its model and sends whatever
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
| More than 25 jobs wait in one queue | Check why the VPS is slow. If another VPS should make some of them, move them with `fleet handover` ([Move work to another VPS](everyday.md#move-work-to-another-vps)) |
| Security updates need a reboot | `fleet reboot <vps>` when no job runs |
| A usage-limit wait longer than 6 hours (a weekly limit) | Nothing to do, unless another VPS should take its queue: [Usage limits](usage-limits.md) |
| A handover stopped halfway (a job has been `outgoing` for more than 10 minutes) | Run the same `fleet handover` again: it finishes the move without making a second copy |
| A VPS's work schedule cannot be read (no job starts there then) | Set it again: [Work schedule](schedule.md) |
| Jobs wait, but the VPS's schedule has no work time in the next 60 days | Change the schedule, or give it extra time with `fleet schedule open` |

Off duty is not a problem: it is what you asked for, so the health check stays quiet
about it.

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

At 9 am, Hermes runs `fleet report` and sends you what it prints:

```
Fleet report for Tue 24 Nov, the last 24 hours
vps1 (Space Facts): 2 video(s) made, 1 queued
vps2 (History): 1 video(s) made, off duty until 18:00
vps3 (Cooking): 0 video(s) made, 1 failed, usage limit until 14:05
Videos with problems:
- vps1 "How far away is the edge of the universe?" (20261124-013002-space-facts-p0x7d): the sound is silent (its loudest moment is -91 dB). Again: fleet retry vps1 20261124-013002-space-facts-p0x7d
Failed:
- vps3 "Five-minute pancakes" (20261124-020011-cooking-a9k2m): timed out after 180m. Again: fleet retry vps3 20261124-020011-cooking-a9k2m
Week plan: 3 video(s) queued, 6 approved and waiting for their day
Published: 1 TikTok inbox upload(s), 2 YouTube draft(s)
Trend looker: 3 look(s), 1 pitch(es), 0 sent to a VPS
Needs you:
- Week plan: 2 topic(s) wait for your yes. Answer "approve all" or "approve 15-16"; see them with: fleet plan show
- Trend looker: pitch 3 for Space Facts waits for your answer: "Why black holes make spaghetti". Say "go 3" or "drop 3"
```

It covers each VPS, the [video check](video-check.md)'s problems, failed jobs, the
[week plan](week-plan.md), what was [published](publishing.md), the
[trend looker](trends.md), and what needs you: the open health problems, topics and
pitches that wait for your answer, and sign-ins that end soon. Run
`fleet report` yourself at any time; `--hours 72` looks back three days.

## Where the messages go

`fleet hermes-cron` delivers to Telegram, into the chat where you sent `/sethome`
(see [Telegram](../home/telegram.md)). To deliver somewhere else Hermes supports, give
the target when you create the jobs, for example `fleet hermes-cron --deliver discord`.
With `--deliver local`, Hermes only saves the messages in its `cron/output/` folder.

## Times and timezone

Hermes reads *"every day at 9am"* in the timezone of its settings. If the report comes
at the wrong hour, set your timezone in the director's settings (`timezone:` in its
`config.yaml`, which `hermes -p director config edit` opens), or give the report its own
timezone:

```
hermes -p director cron edit fleet-report --timezone Europe/London
```

Use your own zone's name from the
[tz database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones). The
10-minute, 30-minute and hourly jobs do not depend on the timezone. The week plan's own
times, and the VPSs' work schedules, are in your PC's time.

## They run only while the gateway runs

The Hermes gateway runs the schedule. While your PC is off, asleep or logged out, no
check runs, but the VPSs keep working. When the gateway is back, the next pull collects
everything and the next health check reports what is still wrong. See
[Keep it running](../home/always-on.md).

## Manage the jobs

```
hermes -p director cron list                        # the jobs and their next run
hermes -p director cron run fleet-report            # run one within the next minute, as an extra
hermes -p director cron pause fleet-health          # stop one for a while
hermes -p director cron resume fleet-health
hermes -p director cron remove fleet-report        # delete one (fleet hermes-cron creates it again)
```

The four script jobs run small Python files that `fleet init` wrote into the director's
`scripts/` folder: `fleet_health.py`, `fleet_pull.py`, `fleet_report.py` and
`fleet_plan.py`. They point at your copy of the
repository and your inventory. To change a threshold of the health check, edit the
argument list in `fleet_health.py`, for example
`["health", "--changes-only", "--min-disk-pct", "10"]`. The options are
`--min-disk-pct` (default 15), `--max-backlog` (default 25) and `--remind-hours`
(default 6); see the [command reference](../reference/cli.md#fleet-health).
`fleet init` and `fleet hermes-cron` write these files again each time they run, so
repeat the edit after them.
