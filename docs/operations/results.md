# Results

Finished jobs come back to your PC with `fleet pull`. Hermes runs it every 30 minutes
and when you ask, so you rarely need to run it yourself.

## Where they go

Into `fleet-results` in your home folder (`%USERPROFILE%\fleet-results` on Windows), one
folder per job:

```
fleet-results/
  index.jsonl                                   one line per pulled job
  vps2/
    20261118-101145-space-facts-a81kd/
      output/                                   the deliverables
        video.mp4
        thumbnail.png
        metadata.json
        SUMMARY.txt                             the session's final message
      logs/
        provider.log                            one line per attempt, and how it ended
        transcript.jsonl                        everything the session did
        claude.stderr                           Claude Code's error output
      result.json                               Claude Code's final result
      status.json                               the worker's record of the job
      job.json                                  the job as it was queued
```

To keep results somewhere else, such as an external disk, set `results_dir` in your
inventory (see [Configuration](../reference/config.md#fleetini)).

## What each file tells you

**`output/SUMMARY.txt`** is the session's last message: what it made and where, and the
choices it made along the way. `fleet pull` prints its first lines.

**`result.json`** is Claude Code's final result event. The useful fields:

| Field | Meaning |
| --- | --- |
| `is_error` | `true` when the session ended with an error. |
| `subtype` | `success`, or the kind of error, such as `error_max_turns`. |
| `num_turns` | How many turns the session took. |
| `duration_ms` | How long it ran, in milliseconds. |
| `total_cost_usd` | Claude Code's estimate of what the session would cost at API prices. With a subscription you do not pay it, but it shows how heavy the job was. |
| `session_id` | The Claude Code session, for the record. |

**`status.json`** is the worker's record: when the job was claimed, started and
finished, its exit code, the reason it failed, how many attempts it took, and how often
it waited for a usage limit.

**`logs/transcript.jsonl`** holds every step of the session as Claude Code's streaming
JSON, one event per line. Earlier attempts are kept as `transcript.1.jsonl`,
`transcript.2.jsonl` and so on. To read just what Claude said, with
[jq](https://jqlang.org/):

```bash
jq -r 'select(.type == "assistant") | .message.content[]? | select(.type == "text") | .text' logs/transcript.jsonl
```

## The index

`fleet-results/index.jsonl` gets one line of JSON for every job pulled, so Hermes (or a
script of yours) can answer questions like *"what did vps3 make this week?"* without
opening every folder. Each line has the job's `id`, `node`, `state` (`done` or
`failed`), `channel`, `title`, `provider`, the `submitted_at`, `started_at` and
`finished_at` times, `duration_s`, `exit_code`, `reason`, `attempts`, `limit_waits`,
`path` (the folder on your PC), `summary` (the first 600 characters of `SUMMARY.txt`)
and `pulled_at`.

## What happens on the VPS

1. When a job finishes, the VPS keeps its whole workspace.
2. `fleet pull` downloads `output/`, `logs/`, `result.json`, `status.json` and `job.json`,
   then marks the job as pulled. `fleet jobs` shows `(pulled)` next to it.
3. Every night (04:30 VPS time, UTC unless you chose another zone, plus up to 30 minutes)
   the VPS deletes the workspaces that were pulled more than 7 days ago.

A job is never deleted before your PC has a copy. A job that is never pulled stays on
the VPS until it is.

If a download breaks, the job is not marked as pulled, and the next pull tries again.
On Linux and macOS, downloads use rsync and continue where they stopped. On Windows,
each job comes as one compressed archive over SSH, which starts over when it breaks.

## Get something that was not downloaded

`fleet pull` brings back only the five parts above. Anything else the session left in
its workspace, such as intermediate renders or downloaded footage, stays on the VPS
until the cleanup. Copy it while it is there; the installer set up SSH so that the
node name is enough:

```
scp vps2:/home/fleet/fleet/work/20261118-101145-space-facts-a81kd/renders/draft.mp4 .
```

To download a job again, remove its pulled mark, then pull:

```
fleet exec vps2 -- rm /home/fleet/fleet/work/20261118-101145-space-facts-a81kd/.pulled
fleet pull vps2
```

## Space on your PC

Videos are large, and the fleet never deletes anything on your PC. Move or delete old
job folders yourself when you no longer need them. The index keeps their lines, so it
remains a record of everything the fleet made.
