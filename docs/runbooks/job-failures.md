# Job failures

**Symptoms:** a job shows as `failed` in `fleet jobs`, or as `[FAILED]` in the pull
message, with a reason next to it.

## Find the reason

```
fleet jobs --state failed
fleet logs vps3 20261118-093010-history-p02xs
```

The `NOTE` column gives the worker's reason. The log gives the provider's side: which
Claude Code version ran, how it signed in, and its last words. After `fleet pull`, the
job's folder in `fleet-results` has more:

| File | What to look for |
| --- | --- |
| `output/SUMMARY.txt` | The session's last message. When a session ends with an error, the error text is here. |
| `result.json` | `is_error`, and `subtype` (for example `error_max_turns`). |
| `logs/provider.log` | One line per attempt and how it ended. |
| `logs/claude.stderr` | Claude Code's own error output. |
| `logs/transcript.jsonl` | Every step the session took. See [Results](../operations/results.md#what-each-file-tells-you) to read it. |

## Reasons and fixes

| Reason | What happened | Fix |
| --- | --- | --- |
| `timed out after 180m` | The job ran longer than its `timeout_minutes`. | [Timed out](#timed-out) |
| `killed (often out of memory; see fleet status)` | The system stopped the job, nearly always for lack of memory. | [Killed](#killed) |
| `provider exited 1` | The Claude session ended with an error. | [The session ended with an error](#the-session-ended-with-an-error) |
| `provider claude has no credentials on vps3` | The VPS has no Claude token or API key. | `fleet secrets push claude vps3`; see [Rotate credentials](rotate-credentials.md) |
| `provider exited 127` | Claude Code is not installed on that VPS. | `fleet provider install claude vps3` |
| `provider claude not available on vps3` | The VPS has no Claude adapter: its fleet code is missing or old. | `fleet sync vps3` |
| `bad job: ...` | The job could not be set up: a missing template, an unsafe file path, or broken base64. | Fix the job; for a missing template, `fleet sync` |
| `cancelled` or `cancelled before it started` | Someone ran `fleet cancel`. | Nothing, or `fleet retry` |
| `lost its process (reboot or crash) and has no retries left` | The VPS rebooted or the job's process died, more often than `max_retries` allows. | `fleet retry`, and check why the VPS rebooted |
| `stopped by a usage limit 50 times; giving up` | The Claude account kept hitting its usage limit. | Check the account's plan; see [Usage limits](../operations/usage-limits.md) |

## Timed out

The job was stopped at its `timeout_minutes` (180 by default, 1440 at most), and filed as
failed. What it made so far is still in its `output/` folder.

- If the work was nearly done, give the job more time: `"timeout_minutes": 300`.
- If it was stuck, read the end of `logs/transcript.jsonl` to see on what. A command that
  waits for input or a download that hangs are typical. Say in the prompt how to avoid
  it.
- Split very long work into several jobs, for example script, then voice-over, then
  edit.

## Killed

The system ended the job without warning, which nearly always means the VPS ran out of
memory: video rendering is memory-hungry, and two heavy renders at once can be too much.
To confirm, ask the VPS:

```
fleet exec vps3 --root -- "dmesg -T | grep -iE 'out of memory|killed process' | tail -n 5"
```

Then:

- Run fewer sessions at once on that VPS: lower `sessions` in your inventory, then
  `fleet bootstrap vps3 --skip-upgrade`.
- Ask for lighter work in the prompt: render at the final size only, use
  `-threads 2` with ffmpeg, avoid loading whole videos into Python.
- Move to a bigger plan in hPanel. See [Create the VPSs](../vps/hostinger.md#choose-a-plan).

`fleet status --json` shows `mem_available_mb` and `mem_total_mb` for each VPS.

## The session ended with an error

`provider exited 1` means Claude Code ran but the session did not end well. The reason
is in the job's log (`claude: the session ended with an error: ...`) and in
`output/SUMMARY.txt`:

| You see | Fix |
| --- | --- |
| `error_max_turns` | The session used all its `max_turns`. Raise it, or make the job smaller. |
| `error_max_budget_usd`, or a message about the budget | The session reached `max_budget_usd`. Raise it if the job is worth it. |
| An error about the API key or token: invalid, expired or revoked | [Rotate credentials](rotate-credentials.md), then `fleet provider check claude vps3 --smoke`. |
| `Claude Code exited with code ...` and lines from `claude.stderr` | Claude Code itself failed. Run `fleet provider check claude vps3 --smoke`. If that fails too, reinstall: `fleet provider install claude vps3`. |
| `error_during_execution` | Something failed during the session. Read the end of `logs/transcript.jsonl` and `logs/claude.stderr`. |

## The job finished, but the result is wrong

The worker files a job as `done` when the session ends without error, whatever it made.
If the video is not what you wanted:

1. Read `output/SUMMARY.txt`: the session lists the choices it made.
2. Read the transcript to see where it went another way.
3. Make the prompt more precise, or put the channel's standing rules in a
   [template](../operations/job-format.md#templates), and run it again.

## Run it again

```
fleet retry vps3 20261118-093010-history-p02xs            # on the same VPS
fleet retry vps3 20261118-093010-history-p02xs --to auto  # on the least busy VPS
```

The copy gets a new id ending in `-r1` and starts in a fresh workspace. `fleet retry`
needs the old workspace on the VPS, which is deleted 7 days after the job was pulled.
After that, send the job again from the copy in your results folder: copy its
`job.json`, delete its `"id"` line, and `fleet dispatch` the copy.

## Job files that were never listed

A job file that is not valid JSON, or has no `prompt`, is moved aside on the VPS as
`jobs/failed/<name>.json.invalid`, and `fleet jobs` does not show it. `fleet dispatch`
checks every job before sending it, so these only appear when a file was put into a
queue by hand.
