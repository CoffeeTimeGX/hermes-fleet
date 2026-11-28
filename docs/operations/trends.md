# Trend looker

The trend looker watches what is rising on YouTube in each channel's niche. When a video
takes off, Hermes pitches you a video on the same subject, with its own angle. Answer
*go 3* and that video is next in the channel's queue. Answer *shift 3* and the rest of
today's videos turn to that subject too. On the studio's pixel lot, the trend looker is
the zeppelin over the lot.

It runs on your PC, beside Hermes, never on a VPS. It only reads public YouTube data,
with your own key, and it makes nothing without your *go* or *shift*.

## How a day goes

1. **At 08:00, 13:00 and 18:00**, Hermes' `fleet-trends` job runs `fleet trends look`.
   It asks YouTube, for each channel, which videos of the last 48 hours in its niche have
   the most views, and works out their views an hour.
2. **When nothing new rises fast**, nothing happens: Hermes is not even woken.
3. **When a video rises fast** (1,000 views an hour or more), Hermes decides whether it
   would make a good video for that channel, and pitches you at most one per channel:

    ```
    New on YouTube for Space Facts: "Black hole spaghetti, explained" by Sky Lab,
    48,000 views in 4 hours.

    Pitch 3, Space Facts: "Why black holes make spaghetti"
    What a black hole does to a star that comes too close, in simple words.

    Answer "go 3" to make it next on vps1, or "drop 3".
    ```

4. **You answer** in the same chat:

    | You write | Hermes runs |
    | --- | --- |
    | *go 3* | `fleet trends go 3` |
    | *shift 3* | `fleet trends shift 3` |
    | *drop 3* | `fleet trends drop 3` |

    *go 3* queues the video on the channel's own VPS, first in its queue. It starts as
    soon as that VPS is free and its [schedule](schedule.md) lets it. *shift 3* does the
    same, and also turns today's other videos to the trend: see
    [Shift the day](#shift-the-day). A pitch you do not answer expires after two days,
    because trends fade.

5. **Each morning**, the [daily report](scheduled-checks.md#the-daily-report) says how
   many looks and pitches there were, and which pitches still wait for your answer.

Only you say go. Hermes pitches, but it never queues a pitch by itself, and a pitch never
moves to another VPS.

## Shift the day

When more videos are planned for today, a pitch can take the rest of the day with it.
Hermes then gives the pitch a new topic on the trend for each of today's videos that no
VPS has yet, and the message lists them under the pitch:

```
Pitch 3, Space Facts: "Why black holes make spaghetti"
What a black hole does to a star that comes too close, in simple words.

"shift 3" also changes today's other videos:
#41 15:00 History on vps2: "How Rome built its roads" becomes "The oldest maps of the stars"
#42 17:00 Cooking on vps3: "One-pan lemon chicken" becomes "What astronauts eat for dinner"

Answer "go 3", "shift 3" or "drop 3".
```

- *go 3* makes only the pitched video. Today's plan stays as it is.
- *shift 3* makes the pitched video next, as *go 3* does, and gives today's other videos
  their new topics. Each one is still made by the same VPS, at the same time: only its
  subject changes. Your *shift* is the yes for those topics, so there is nothing more to
  approve.
- *drop 3* lets it go.

A video that a VPS already has, or that you changed since the pitch, keeps its topic. So
do the videos of a channel the trend looker does not watch (`fleet trends watch
"<channel>" --off`). A pitch changes at most 8 videos, the soonest first. *shift* works on
the day of the pitch; the day after, the pitched video alone is made.

On the pixel lot, the zeppelin's banner asks **SHIFT 3?**, and flyers flutter down onto
the roofs of the stages whose videos would change. Click a stage to read what would change
there.

`fleet plan show` marks each video a shift changed: `(shifted from History by pitch 3, made
on vps2)`. Change one back like any planned video, with `fleet plan edit 41 --title "..."`,
or leave it out with `fleet plan reject 41`.

## One channel, several subjects

The trend looker watches each channel of the fleet on its own. When your YouTube channel
covers several subjects, make each subject a channel of the fleet, one VPS each: for
example `channels = Space` for vps1 and `channels = Animals` for vps2 in `fleet.ini`. Then:

- each subject has its own words to watch: `fleet trends watch "Space" --words "black
  holes, planets"`;
- each subject has its own days, time and ideas in the [week plan](week-plan.md);
- when one subject trends, *shift* turns the rest of the day to it, each video on its
  usual VPS and at its usual time;
- to [publish](publishing.md), sign each subject in to the same YouTube channel:
  `fleet publish --login youtube --channel "Space"`, and pick that channel each time.

## Set it up

**1. Make a YouTube API key.** It is free. You can use the Google Cloud project you made
for [publishing](publishing.md#youtube), or a new one.

1. Open the [Google Cloud console](https://console.cloud.google.com/) and pick the
   project (or create one).
2. Open **APIs & Services**, then **Library**. Find **YouTube Data API v3** and click
   **Enable** (if it says **Manage**, it is already on).
3. Open **APIs & Services**, then **Credentials**. Click **Create credentials**, then
   **API key**.
4. Under **API restrictions**, choose **Restrict key** and tick **YouTube Data API v3**.
   Then the key works for nothing else. Leave **Authenticate API calls through a service
   account** unticked, and click **Create**.
5. Copy the key from the **API key created** box. (If your console made the key at once,
   without asking, click the key's name, do step 4 there and click **Save**.)

**2. Give it to the fleet,** in a terminal on your PC:

```powershell
fleet trends key
```

Paste the key and press Enter. It stays hidden while you paste. The fleet checks the key
with Google, then saves it in `~/.config/fleet/secrets/publish/youtube-api-key.json`
(on Windows, `%USERPROFILE%\.config\fleet\secrets\publish\`). Never send the key in a
chat, Hermes' included.

**3. Create Hermes' job:**

```powershell
fleet hermes-cron
```

It adds `fleet-trends` and leaves the jobs you already have.

**4. Look once now,** to see it work:

```powershell
fleet trends look
```

It prints what it found for each channel. `fleet trends` shows the last look again
without asking YouTube.

## What it looks for

For each channel it searches for the channel's first sentence of `ideas` in its
[week plan](week-plan.md#each-channels-days-and-time) file, split at commas and "and".
A channel without one is searched by its name. Give a channel its own words:

```powershell
fleet trends watch "Cooking" --words "air fryer, one pan dinners"
```

| Option | What it does |
| --- | --- |
| `--words "a, b"` | What to search for, up to 8 words or short phrases. `--words ""` goes back to the week plan ideas. |
| `--region US` | Only what is popular in one country (a two-letter code). `--region ""` for anywhere. |
| `--language en` | Prefer videos in one language. `--language ""` for any. |
| `--min 2000` | The views an hour that count as rising. The default is 1,000. |
| `--off` and `--on` | Stop looking for a channel, and start again. |

`fleet trends` shows what each channel watches, its last finds, and the pitches.

## How much it costs

Nothing. Google gives each Cloud project 10,000 units of YouTube quota a day, and starts
again at midnight, Pacific time. A look at one channel uses 101 units: a search (100) and
the videos' numbers (1). Three looks a day at 5 channels use about 1,500.

The trend looker stops at 2,000 units a day, so the rest of the project's quota stays for
uploads if you [publish](publishing.md) from the same project. Change the limit with
`trends_budget` in the `[defaults]` part of `fleet.ini`.

## Good to know

- It watches YouTube only, through Google's official YouTube Data API.
- A video counts once: after Hermes has seen it, it is not news again.
- A channel gets one pitch at a time. While a pitch waits, and for 20 hours after one,
  the channel is not pitched again.
- *go* puts the video first in its channel's queue, behind a job that a usage limit
  stopped, which goes on first. A video already running is not interrupted.
- `fleet dispatch --first` does the same for any job: it starts before the other jobs in
  its VPS's queue.
- The pitches and the last looks are kept in `~/.config/fleet/trends.json`.
- With no key yet, the zeppelin floats over the lot with its board dark, and its card
  says how to start it.
