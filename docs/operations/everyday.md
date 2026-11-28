# Everyday use

Most days you only talk to the director (Hermes' `director` profile), in the terminal
(`hermes -p director`) or on Telegram. It turns what you ask into `fleet` commands,
runs them and reports back. This page shows what to ask and the commands behind it, so
you can also run them yourself.

Run `fleet` commands from any terminal: PowerShell, cmd or Git Bash on Windows, any
shell on Linux and macOS.

## A normal day

1. **Queue the work.** Tell the director what to make: *"Make three shorts for Space
   Facts: Saturn's rings, Europa's ocean and the Kuiper belt."* It writes one job per
   video and queues them on the VPS that makes Space Facts.
2. **Do something else.** Each VPS works through its queue on its own, also while your
   PC is off.
3. **Get the results.** Every 30 minutes Hermes downloads what finished and sends you a
   message with each job's summary and what the [video check](video-check.md) found.
   Each morning at 9 it sends a short report on the whole fleet.
4. **Publish.** Send the good ones to YouTube, TikTok or Instagram with
   [`fleet publish`](publishing.md), or ask Hermes to.
5. **Deal with problems when Hermes tells you.** The health check messages you only
   when something changes: a VPS stops answering, a job fails, the disk gets low.

On Sundays Hermes also sends you next week's topics to approve. See
[Week plan](week-plan.md). And when a video takes off on YouTube in one of your channels'
niches, Hermes pitches you a video on it: answer *go 3* to make it next, or *shift 3* to
turn the rest of today's videos to that subject too. See [Trend looker](trends.md).

## What to ask, and what Hermes runs

| You ask | Hermes runs |
| --- | --- |
| *"How is the fleet?"* | `fleet status` |
| *"Anything wrong?"* | `fleet health` |
| *"Make a 60-second short for Space Facts about Saturn's rings."* | writes a job file, then `fleet dispatch <file>` |
| *"Run this on vps2 only."* | `fleet dispatch <file> --to vps2` |
| *"Test every VPS."* | `fleet dispatch jobs/examples/hello-fleet.json --to all` |
| *"What is running?"* | `fleet jobs --state running` |
| *"Show me what vps3 is doing."* | `fleet logs vps3 <job-id>` |
| *"Collect the finished videos."* | `fleet pull` |
| *"Stop that job."* | `fleet cancel vps3 <job-id>` |
| *"Try that one again on vps4."* | `fleet retry vps3 <job-id> --to vps4` |
| *"Move vps2's waiting jobs to vps4."* | `fleet handover vps2 vps4` |
| *"Pause vps2, I want to update it."* | `fleet pause vps2` |
| *"Start vps2 again."* | `fleet resume vps2` |
| *"Is that video all right?"* | `fleet check vps1 <job-id>` |
| *"What happened yesterday?"* | `fleet report` |
| *"Plan next week."* | `fleet plan slots --week next`, then `fleet plan import <file>` |
| *"Approve all."* or *"Approve 12-14."* | `fleet plan approve all` or `fleet plan approve 12-14` |
| *"What's trending?"* | `fleet trends` |
| *"Go 3."* or *"Drop 3."* | `fleet trends go 3` or `fleet trends drop 3` |
| *"Shift 3."* | `fleet trends shift 3` |
| *"Put that video on YouTube and TikTok."* | `fleet publish vps1 <job-id> --to youtube,tiktok` |
| *"vps1 should only work 8 to 11 pm."* | `fleet schedule set vps1 --hours 20:00-23:00` |
| *"Let vps1 work for two more hours."* | `fleet schedule open vps1 --for 2h` |
| *"Idea: a weekly summary on Sunday evenings."* | `fleet ideas add "Weekly summary" --note "..."` |
| *"What ideas do we have?"* | `fleet ideas` |

For anything that changes a server (closing SSH, rebooting, deleting) or moves work to
another VPS, the director says what it will run and waits for your yes. It approves no
week plan topic, says go or shift to no trend pitch, posts nothing to Instagram and changes
no schedule unless you ask.

## Check the fleet

```
fleet status
```

```
NODE  SERVICE                   QUEUED  RUNNING  DONE  FAILED  UNPULLED  DISK FREE      LOAD  PROVIDERS
vps1  active                    0       1/1      12    1       0         71.3 GB (74%)  1.92  claude:ok
vps2  active                    2       1/1      9     0       1         68.0 GB (71%)  2.1   claude:ok
vps3  active LIMIT until 17:05  1       0/1      14    0       0         70.2 GB (73%)  0.04  claude:ok
vps4  active PAUSED             0       0/1      7     0       0         74.9 GB (78%)  0.0   claude:ok
vps5  UNREACHABLE               -       -        -     -       -         -              -     ssh: connect to host vps5 port 22: Connection timed out
```

| Column | Meaning |
| --- | --- |
| `SERVICE` | `active` when the worker runs. `PAUSED` after `fleet pause`. `LIMIT until 17:05` while the Claude account waits for its usage limit to reset (in your PC's local time). `OFF DUTY until 08:00` outside the VPS's [work schedule](schedule.md). `UNREACHABLE` when your PC cannot reach the VPS; the last column says why. |
| `QUEUED` | Jobs waiting to start. |
| `RUNNING` | Jobs running now, out of how many the VPS may run at once (`sessions` in your inventory). |
| `DONE`, `FAILED` | Finished jobs still on the VPS. Pulled jobs stay listed until the nightly cleanup deletes them, 7 days after the pull. |
| `UNPULLED` | Finished jobs your PC has not downloaded yet. |
| `DISK FREE` | Free space on the VPS. New jobs stop starting under 3 GB. |
| `LOAD` | The VPS's load average over the last minute. Above its number of CPUs, it is busy. |
| `PROVIDERS` | `claude:ok`, `claude:BAD` (with the reason in `fleet health`) or `claude:not-installed`. |

`fleet health` prints only the problems, each with the command or page that fixes it.
It exits with code 2 when there are problems, which makes it easy to use in scripts.

## Queue work

The quickest way is a one-line job:

```
fleet dispatch --prompt "Make a 30-second vertical teaser for ..." --channel "Space Facts"
```

For real work, write a job file. Hermes keeps them in `fleet-jobs/` in your home
folder. Only `prompt` is required:

```json
{
  "channel": "Space Facts",
  "title": "Saturn's rings in 60 seconds",
  "prompt": "Make one vertical short (1080x1920, 45 to 60 seconds) about Saturn's rings ...",
  "timeout_minutes": 180
}
```

```
fleet dispatch ~/fleet-jobs/saturn-rings.json
```

```
queued 20261118-142233-space-facts-k3x9p on vps2 (channel Space Facts, provider claude)
```

`fleet dispatch` puts the job on the VPS that makes videos for its channel: the
`channels` line of each VPS in your inventory (see [Configuration](../reference/config.md#fleetini)).
If that VPS is busy, paused or waiting for a usage limit, the job waits in its queue
there, and the command says so. If the VPS does not answer, or Claude is not set up on
it, the command refuses the job and says why. Work never moves to another VPS by
itself. When several VPSs make the same channel, the least busy one that can start the
job gets it. A channel that no VPS names goes to a VPS with `channels = all` if you have
one; otherwise `fleet dispatch` refuses the job and says why. Other choices:

- `--to vps2` puts it on vps2, whatever its channel (you get a note, and a warning if
  vps2 cannot start it soon).
- `--to vps2,vps4` picks the least busy of the two.
- `--to all` puts a copy on every VPS (the copies get `-vps1`, `-vps2` and so on at the
  end of their ids).
- `--dry-run` prints the job as it would be queued, without queuing it.
- Several files at once: `fleet dispatch ~/fleet-jobs/*.json`. This works in PowerShell
  and cmd too: `fleet` expands the `*` itself.

Every field of a job file is described in [Job format](job-format.md).

## Follow progress

```
fleet jobs
```

```
NODE  STATE    ID                                 CHANNEL      STARTED               FINISHED              NOTE
vps1  running  20261118-141502-history-7fq2m      History      2026-11-18T14:15:07Z  -
vps2  inbox    20261118-142233-space-facts-k3x9p  Space Facts  -                     -
vps2  done     20261118-101145-space-facts-a81kd  Space Facts  2026-11-18T10:11:50Z  2026-11-18T11:02:13Z  (pulled)
vps3  failed   20261118-093010-history-p02xs      History      2026-11-18T09:30:15Z  2026-11-18T12:30:16Z  timed out after 180m
```

Job times are in UTC (the `Z` at the end). Narrow the list with a VPS name or a state:
`fleet jobs vps2 --state failed`. States are `inbox` (waiting), `running`, `done`,
`failed`, `outgoing` (being handed over to another VPS) and `moved` (handed over after
it had started; what it made waits for the pull).

To watch a job, show the last lines of its log:

```
fleet logs vps1 20261118-141502-history-7fq2m
fleet logs vps1 20261118-141502-history-7fq2m -f     # keep following; Ctrl+C to stop
```

The log shows the Claude Code version, how the session signed in, and how it ended.
The full record of what the session did is `logs/transcript.jsonl`, which comes with
the results.

To watch the whole fleet at once, open the studio:

```
fleet studio
```

Your browser shows every VPS as a sound stage, with what each session is doing right
now, and it refreshes by itself. Click **Pixel lot** at the top to see the same fleet as
a pixel-art studio, where everyone at work stands for something real.
`fleet studio --tailnet` lets your phone watch too. See [The studio](studio.md).

## Collect the results

```
fleet pull
```

```
Pulled 2 finished job(s) into /home/you/fleet-results:
[done] vps2/20261118-101145-space-facts-a81kd  channel: Space Facts
    /home/you/fleet-results/vps2/20261118-101145-space-facts-a81kd
    Made a 58-second vertical short about Saturn's rings. Files in ./output/: video.mp4, thumbnail.png, script.md, metadata.json. ...
[FAILED] vps3/20261118-093010-history-p02xs  channel: History (timed out after 180m)
    /home/you/fleet-results/vps3/20261118-093010-history-p02xs
    log: claude: 2.1.300 (Claude Code) | subscription token | mode bypassPermissions | max turns 300
```

Hermes runs this every 30 minutes by itself. The videos and everything else a job made
are in `output/` inside each job's folder. See [Results](results.md).

## Fix a job

- **Stop it:** `fleet cancel vps1 <job-id>`. A waiting job is removed from the queue; a
  running one is stopped and filed as `failed` with the note `cancelled`.
- **Run it again:** `fleet retry vps3 <job-id>` queues a fresh copy on the same VPS,
  with `-r1` added to the id (then `-r2` and so on). Add `--to vps4` to run it on vps4
  instead.
- **Find out why it failed:** the `NOTE` column of `fleet jobs` and the pull message
  give the reason. [Job failures](../runbooks/job-failures.md) explains each one.

## Move work to another VPS

Work stays on its channel's VPS unless you move it. When a VPS will be stuck for a
while, for example at its weekly usage limit, move its waiting jobs yourself, or ask the
director to: *"Move vps2's waiting jobs to vps4."*

```
fleet handover vps2 vps4 --dry-run     # show what would move
fleet handover vps2 vps4               # move every waiting job
fleet handover vps2 vps4 <job-id>      # move only this one
```

```
moved 20261118-142233-space-facts-k3x9p (channel Space Facts) from vps2 to vps4
note: only these jobs moved. New Space Facts jobs still go to the VPS that fleet.ini names for that channel.
```

- The jobs keep their ids and wait in vps4's queue. If vps4 already has a job with the
  same id, the moved one gets `-h1` at the end.
- Running jobs stay where they are. To move one anyway, stop it and run it again on the
  other VPS: `fleet cancel vps2 <job-id>`, then `fleet retry vps2 <job-id> --to vps4`.
- A job that had already started on vps2, for example one that hit the usage limit
  halfway, starts over on vps4. What it made on vps2 comes home with the next pull,
  marked `[MOVED]`.
- New jobs for vps2's channel still go to vps2. To give the channel to another VPS for
  good, change `channels` in your inventory.

## Pause a VPS

```
fleet pause vps2 --reason "updating"
fleet resume vps2
```

A paused VPS starts no new jobs. Running jobs finish normally and the queue waits. New
jobs for its channel wait there too, unless you move them with `fleet handover`.
`fleet resume` also ends a usage-limit wait early (see [Usage limits](usage-limits.md)).

## Where to go next

- [The studio](studio.md): watch every VPS at work in your browser.
- [Work schedule](schedule.md): the hours each VPS works.
- [Week plan](week-plan.md), [Trend looker](trends.md), [Video check](video-check.md) and [Publishing](publishing.md).
- [Job format](job-format.md): every setting a job can have.
- [Scheduled checks](scheduled-checks.md): what Hermes checks and when it messages you.
- [Runbooks](../runbooks/index.md): what to do when something goes wrong.
- [Command reference](../reference/cli.md): every `fleet` command and option.
