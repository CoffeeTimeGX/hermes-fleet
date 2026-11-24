# Video check

After each job that ends well, the VPS looks at the video before the job counts as done.
It never fails the job. It says what is wrong, and you decide.

```powershell
fleet jobs vps1
```

```
NODE  STATE  ID                                 CHANNEL      STARTED               FINISHED              NOTE
vps1  done   20261124-090012-space-facts-k2m9q  Space Facts  2026-11-24T09:00:14Z  2026-11-24T09:41:52Z  video ok
vps1  done   20261124-130020-space-facts-p0x7d  Space Facts  2026-11-24T13:00:21Z  2026-11-24T13:38:03Z  CHECK: the sound is silent (its loudest moment is -91 dB) (+1 more)
```

The same verdict comes with the message of `fleet pull`, and the
[daily report](scheduled-checks.md#the-daily-report) lists the videos with problems,
with the command to make them again.

## What it looks at

| It checks | A problem when |
| --- | --- |
| The video | There is no video in `output/`, it cannot be read, it has no picture, or it lasts 0 seconds. |
| The picture | 80% of its key frames are black. |
| The sound | It has no sound track, or its loudest moment is below -50 dB (silent). |
| The thumbnail | There is no `thumbnail.png` or `thumbnail.jpg` (also `thumb`, `cover` or `poster`), or it is less than 640 pixels wide. 1280x720 is best. |
| The details | `output/metadata.json` is missing or is not valid JSON, or it has no title. The title may have 100 characters, the description 5000 and the tags 500, with no `<` or `>`: YouTube's own limits. |
| Your wishes | The length, size or shape the job asks for (see below). |

The video is `output/video.mp4` when there is one. Otherwise it is the biggest video in
`output/`, preferring a name with "final" or "video" in it. The check uses `ffprobe` and
`ffmpeg`, which the bootstrap installs. Without them, the job is marked
`not checked: ffprobe is not installed on this VPS`.

## Ask for more, or for less

Add `checks` to the job file, or to the channel's file in `channels/` (see
[Week plan](week-plan.md)):

```json
{
  "channel": "Space Facts",
  "prompt": "...",
  "checks": {"min_seconds": 45, "max_seconds": 60, "vertical": true, "max_megabytes": 300}
}
```

| Key | Meaning | Default |
| --- | --- | --- |
| `min_seconds`, `max_seconds` | The shortest and longest the video may be. | no limit |
| `width`, `height` | The exact size in pixels, like `1080` and `1920`. | any |
| `vertical` | `true` for a vertical video (a short), `false` for landscape. | either |
| `max_megabytes` | The largest file. | no limit |
| `audio` | `false` when the video has no sound on purpose. | on |
| `thumbnail` | `false` when the job makes no thumbnail. | on |
| `metadata` | `false` when the job writes no `metadata.json`. | on |
| `video` | The video to check, such as `output/final.mp4`. | found by itself |

`"checks": false` turns the check off for that job.

## Check a video again

After you fix a file by hand, or after `fleet sync` brought a newer check, look again:

```powershell
fleet check vps1 20261124-130020-space-facts-p0x7d
```

```
vps1/20261124-130020-space-facts-p0x7d: 2 problem(s):
  - the sound is silent (its loudest moment is -91 dB)
  - no thumbnail in output/ (thumbnail.png or thumbnail.jpg)
  output/video.mp4: 52 s, 1080x1920, 30 fps, 14.2 MB, h264+aac, loudest moment -91 dB
  title: How far away is the edge of the universe?
```

It exits with 2 when it finds problems. When the job is already on your PC, its copy of
the verdict is updated too. A job that is still running is checked when it ends.

## What to do with a problem

- **Make it again:** `fleet retry vps1 <job-id>` queues a fresh copy on the same VPS.
- **Fix it by hand:** change the file in the job's folder on your PC. To publish it as it
  is, use `fleet publish ... --anyway` (see [Publishing](publishing.md)).
- **Change the brief:** most problems come from the prompt. Say exactly what the job
  must leave in `output/`, for example *"a 1080x1920 video.mp4 with a voice-over"*.

## Where the verdict is kept

On the VPS and in the job's folder on your PC, `logs/check.json` holds the full verdict:

```json
{"ok": false, "problems": ["the sound is silent (its loudest moment is -91 dB)"],
 "video": "output/video.mp4", "facts": {"seconds": 52.4, "width": 1080, "height": 1920},
 "checked_at": "2026-11-24T13:38:05Z", "version": 1}
```

`ok` is `true` when all is well, `false` with the problems, and `null` when the check
did not run (`skipped` says why). The job's `logs/check.log` has the check's own errors.
