# Week plan

Every Sunday, Hermes plans next week's videos and sends you the list on Telegram. You
answer with the ones you want. Each approved topic is queued on its channel's VPS on its
day. Nothing is made without your yes.

## How a week goes

1. **Sunday at 10:00**, Hermes looks for next week's open slots, gives each one a new
   topic that suits its channel, and adds them to the plan as drafts.
2. **It sends you the plan:**

    ```
    Monday 30 November
      #12 09:00 Space Facts: "Why Saturn's rings are vanishing" [draft]
      #13 09:00 History: "The last day of Pompeii" [draft]
    Wednesday 02 December
      #14 09:00 Space Facts: "How far away is the edge of the universe?" [draft]

    3 topic(s) wait for the owner's yes: fleet plan approve 12-14 (or all)
    ```

3. **You answer** in the same chat:

    | You write | Hermes runs |
    | --- | --- |
    | *approve all* | `fleet plan approve all` |
    | *approve 12-13* | `fleet plan approve 12-13` |
    | *reject 14* | `fleet plan reject 14` |
    | *13: make it about Herculaneum* | `fleet plan edit 13 --title "..." --brief "..."` |

4. **Every hour**, the fleet queues the approved topics whose time has come, each on its
   channel's VPS. The VPS starts it when its [schedule](schedule.md) lets it.
5. **Each morning**, the [daily report](scheduled-checks.md#the-daily-report) says what
   was queued and which topics still wait for your answer.

Only you approve. Hermes adds drafts and changes them when you ask, but it never
approves a topic by itself. A draft that gets no answer is never made.

## Each channel's days and time

Without settings, every channel gets one video a day, queued at 09:00 in your PC's time.
To change that, give the channel a file of its own, `channels/<channel>.json`, next to
your inventory. The file name is the channel's name in small letters, with `-` for
spaces: `~/.config/fleet/channels/space-facts.json` for Space Facts.

```json
{
  "channel": "Space Facts",
  "plan": {
    "days": "mon,wed,fri",
    "time": "07:30",
    "ideas": "Planets, moons and space missions. Surprising facts, one per video."
  }
}
```

| Key | Meaning |
| --- | --- |
| `days` | `daily` (the default), `weekdays`, `weekends`, or days such as `mon,wed,fri`. |
| `time` | When the job is queued, in your PC's time, like `07:30`. The default is `09:00`. |
| `ideas` | A few words for Hermes about the channel's topics. |

The rest of the file is a [job file](job-format.md) for the channel's videos: its
`prompt`, `template`, `files`, `model`, `timeout_minutes` and the rest. In the prompt and
in the files, the fleet fills in `{title}`, `{brief}`, `{day}` and `{channel}`. It also
writes the topic into the workspace as `topic.md`.

```json
{
  "channel": "Space Facts",
  "plan": {"days": "mon,wed,fri", "time": "07:30"},
  "prompt_file": "space-facts-prompt.md",
  "timeout_minutes": 120,
  "checks": {"min_seconds": 45, "max_seconds": 60, "vertical": true}
}
```

`prompt_file` is read from the `channels` folder. Without a prompt, the fleet uses its
own: a video for the channel on the topic, with `video.mp4`, `thumbnail.png`,
`script.md` and `metadata.json` in `output/`. Those are the files
[publishing](publishing.md) needs.

## Plan by hand

Everything Hermes does, you can do too:

```powershell
fleet plan show                     # what is planned, from today on
fleet plan show --week next         # next week only (also: this, all)
fleet plan slots --week next        # the open slots
fleet plan add --channel "Space Facts" --day 2026-12-02 --title "Why is Mars red?" --brief "Iron, rust and dust storms."
fleet plan import topics.json       # many at once
fleet plan approve 12-14            # or: 12 13, or all
fleet plan reject 15
fleet plan edit 13 --title "The last day of Herculaneum"
fleet plan remove 15
fleet plan run --dry-run            # the jobs that are due now, queued nowhere
```

`fleet plan import` takes a JSON list. `time` is optional, and the channel's own time
is used without it:

```json
[
  {"channel": "Space Facts", "day": "2026-12-02", "title": "Why is Mars red?", "brief": "Iron, rust and dust storms."},
  {"channel": "History", "day": "2026-12-02", "time": "10:00", "title": "Who built Stonehenge?", "brief": ""}
]
```

New topics are drafts until you approve them. A topic already planned for the same
channel, day and time is skipped. A topic that is already queued cannot be changed
here: change or cancel its job instead.

## Good to know

- **A late yes still counts.** A topic you approve after its time is queued at the next
  hourly run.
- **Work stays on its channel's VPS.** When that VPS cannot be reached, the topic waits
  and is tried again every hour. The report tells you.
- **The schedule decides when it starts.** The plan's time is when the job joins the
  queue. A VPS that is off duty starts it in its next work time.
- **Old topics leave the plan.** Queued and rejected topics older than 60 days are
  removed from it. The plan is `~/.config/fleet/plan.json`.
- **Change Sunday's run** with `hermes -p director cron edit fleet-week-plan`, or run it
  now with `hermes -p director cron run fleet-week-plan`. See
  [Scheduled checks](scheduled-checks.md).
