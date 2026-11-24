# Work schedule

Each VPS can have a schedule: the hours it works, pauses between videos, random start
times, days off and a daily cap. The schedule trumps everything. No job starts outside
it, whoever queued it: Hermes, the week plan, a retry or you. A job that is already
running always finishes.

Without a schedule a VPS works 24/7. That is how every VPS starts.

The schedule lives on the VPS itself, so it keeps working while your PC is off. Jobs that
come in outside it wait in that VPS's queue. They never move to another VPS.

## Quick start

Work from 08:00 to 23:00 every day, in your local time:

```powershell
fleet schedule set vps1 --hours 08:00-23:00
```

See what each VPS does now:

```powershell
fleet schedule
```

```
vps1 (Space Facts): works 08:00-23:00. Times in Europe/Paris.
  now: off duty until 08:00
  Wed: work time 08:00-23:00; 0 started
vps2 (History): works 24/7
```

Back to 24/7:

```powershell
fleet schedule set vps1 24/7
```

You can also ask Hermes on Telegram, for example *"vps1 should only work 8 to 11 pm"*.
Hermes runs the same commands.

## The modes

Each option below changes only itself. The others stay as they were. `24/7` at the start
clears everything first: `fleet schedule set vps1 24/7 --cap 3` means "around the clock,
at most 3 videos a day".

| You want | Command |
| --- | --- |
| 24/7, the default | `fleet schedule set vps1 24/7` |
| Your own hours | `fleet schedule set vps1 --hours 08:00-12:00,14:00-23:00` |
| A night shift (videos ready in the morning) | `fleet schedule set vps1 --hours 22:00-07:00` |
| Work in blocks with rests: 3 hours on, 1 hour off | `fleet schedule set vps1 --cycle 3h/1h` |
| A pause after each video | `fleet schedule set vps1 --gap 45m` |
| Random start times, 4 a day | `fleet schedule set vps1 --random 4/day` |
| Weekdays only | `fleet schedule set vps1 --days mon-fri` |
| Days off | `fleet schedule set vps1 --off 2026-12-24..2026-12-26,2027-01-01` |
| At most 3 videos a day | `fleet schedule set vps1 --cap 3` |
| Extra time now, outside the schedule | `fleet schedule open vps1 --for 2h` |

Options combine. This one works weekdays from 08:00 to 23:00, starts at 4 random times a
day, at least an hour apart, and makes at most 3 videos:

```powershell
fleet schedule set vps1 --hours 08:00-23:00 --days mon-fri --random 4/day --min-gap 1h --cap 3
```

Use `all` or a list for several VPSs at once: `fleet schedule set all --hours 08:00-23:00`,
or `fleet schedule set vps1,vps3 --gap 30m`.

### Your own hours

`--hours` takes one or more work windows, separated by commas. `8-12,14-23` works too. A
window may cross midnight, like `22:00-07:00`. It belongs to the day it starts on, so with
`--days mon-fri` the Friday night runs until Saturday 07:00.

A job may start at any time inside a window. Outside the windows the VPS is off duty.

### Work with pauses

There are two kinds of pause, and you can use both:

- `--gap 45m` rests 45 minutes after each video ends, whether it worked or failed.
- `--cycle 3h/1h` works in blocks: 3 hours of work, then 1 hour of rest, and again. The
  blocks start at the beginning of each work window, or at midnight without `--hours`.

Times can be written `45m`, `90` (minutes), `2h`, `1h30` or `1.5h`.

### Random start times

`--random 4/day` picks 4 start times a day at random inside the work time. Each one lets
one job start. When nothing is queued at that time, it stays good until the next one, so a
job that comes in later still starts. Two jobs never start together.

`--min-gap 1h` keeps the start times at least an hour apart. The default is 30 minutes.
When the work time is too short for that, the times are spread out evenly instead.

The times change every day and are different on each VPS. They stay the same all day, so
`fleet schedule` can show them:

```
vps1 (Space Facts): works 08:00-23:00; 4 random start times a day, at least 1h apart. Times in Europe/Paris.
  now: next random start at 15:05
  today: work time 08:00-23:00; random starts 09:12 (used), 11:40 (missed), 15:05, 19:30; 1 started
```

`used` means a job started on it, `missed` that nothing was queued before the next one
came, and `now` that it is waiting for a job.

### Days and days off

- `--days mon-fri`, `--days weekends`, `--days mon,wed,fri` or `--days all`.
- `--off` takes dates and ranges: `2026-12-24..2026-12-26`, `2027-01-01`, `today` or
  `tomorrow`. It replaces the earlier list; `fleet schedule show` lists it. `--off none`
  clears it. Ranges that are over leave the list by themselves.

### A daily cap

`--cap 3` starts at most 3 jobs in one work day. A job that went back to the queue at a
usage limit and starts again counts once.

### Extra time

`fleet schedule open vps1 --for 2h` lets the VPS work for the next two hours, whatever its
schedule says: hours, pauses, random times and the cap. The default is one hour.
`fleet schedule close vps1` ends it early.

### Take an option away

| Option | Off |
| --- | --- |
| `--hours` | `--hours all` |
| `--days` | `--days all` |
| `--off` | `--off none` |
| `--cycle` | `--cycle off` |
| `--gap` | `--gap 0` |
| `--random` | `--random off` |
| `--cap` | `--cap 0` |

## Time zone

The times you type are in your local time. The fleet takes the time zone from, in order:

1. `--tz Europe/Paris` on the command,
2. `timezone` under `[defaults]` in your inventory (see [Configuration files](../reference/config.md)),
3. your PC.

On Windows, Python cannot read the name of your time zone, so the fleet uses your PC's
offset from UTC at that moment, like `+01:00`. That offset does not follow summer time. To
follow it, add the name of your zone to the inventory once, then set the schedule again:

```ini
[defaults]
timezone = Europe/Paris
```

The name comes from the list of tz database names, like `Europe/Paris` or
`America/New_York`.

## How it shows

`fleet status` adds `OFF DUTY until 08:00` to the VPS. `fleet dispatch` says
`held by its schedule (off duty until 08:00)` and queues the job there anyway. The studio
board gives the stage a blue lamp and the words "Off duty", and on the pixel lot a night
watchman sits by the door next to a sign that says when the stage opens again.

The daily report adds the reason to the VPS's line. `fleet health` stays quiet about a
schedule: off duty is what you asked for. It tells you when a schedule cannot be read (no
job starts then, see below), or when jobs wait and the schedule has no work time in the
next 60 days.

## Good to know

- **It trumps everything.** `fleet resume` ends a pause, not the schedule. `fleet pause`
  still works inside the work time. A usage limit still holds the queue in the work time.
- **Running jobs finish.** A job that starts at 22:55 runs past 23:00.
- **A schedule that cannot be read starts nothing.** If `schedule.json` on the VPS is
  damaged, the VPS starts no job, and `fleet health` says so. Set the schedule again to
  mend it.
- **It survives** `fleet sync`, `fleet restart` and `fleet bootstrap`. After you rebuild a
  VPS, set its schedule again.
- **One account per VPS still holds.** A schedule only says when this VPS's own Claude
  account works. It never changes accounts.

## More ideas

These are not built yet. Ask if you want one:

- **Ready by publish time**: start each planned video early enough to be done by the time
  it should go out, from how long the last videos took.
- **Spread the week's usage**: pace each VPS so that its Claude plan's weekly limit lasts
  all week.
- **Quiet hours for messages**: Hermes keeps routine Telegram messages until the morning.
