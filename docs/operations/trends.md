# Trend looker

The trend looker watches what is rising on YouTube in each channel's niche. When a video
takes off, Hermes pitches you a video on the same subject, with its own angle. Answer
*go 3* and that video is next in the channel's queue. On the studio's pixel lot, the
trend looker is the zeppelin over the lot.

It runs on your PC, beside Hermes, never on a VPS. It only reads public YouTube data,
with your own key, and it makes nothing without your *go*.

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
    | *drop 3* | `fleet trends drop 3` |

    *go 3* queues the video on the channel's own VPS, first in its queue. It starts as
    soon as that VPS is free and its [schedule](schedule.md) lets it. A pitch you do not
    answer expires after two days, because trends fade.

5. **Each morning**, the [daily report](scheduled-checks.md#the-daily-report) says how
   many looks and pitches there were, and which pitches still wait for your answer.

Only you say go. Hermes pitches, but it never queues a pitch by itself, and a pitch never
moves to another VPS.

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
