# Provider adapters

Each folder here teaches the VPS worker how to run one kind of LLM session.
Today there is one provider, `claude` (Claude Code). Every VPS runs it.

```
providers/<name>/
  install.sh   install or update the tool for the fleet user (never as root)
  run.sh       run ONE job: run.sh <job.json> <workspace>
  check.sh     health check: --json prints one JSON object, --smoke does a real call
```

## The contract

`fleet-worker` calls `run.sh <job.json> <workspace>` inside its own session, with a
time limit, and with these environment variables set:

| Variable | Meaning |
| --- | --- |
| `FLEET_NODE` | the node name, for example `vps2` |
| `FLEET_JOB_ID` | the job id |
| `FLEET_WORKDIR` | the job's workspace (same as the second argument) |
| `FLEET_OUTPUT_DIR` | `<workspace>/output`, where deliverables go |
| `TMPDIR` | a private temp folder inside the workspace, removed after the job |

An adapter must:

1. Work inside the workspace and put every deliverable in `output/`. Its own logs go in
   `logs/` (the worker already sends the adapter's stdout and stderr to
   `logs/provider.log`).
2. Write `result.json` (a JSON object; include `is_error`) and `output/SUMMARY.txt`
   (a few lines a human can read on their phone).
3. Exit with one of these codes:

   | Exit code | Meaning | What the worker does |
   | --- | --- | --- |
   | `0` | success | files the job as done |
   | `75` | the account hit a usage limit | puts the job back at the front of the queue and starts nothing until the limit resets |
   | `78` | no credentials | fails the job with "no credentials" |
   | anything else | failure | fails the job with "provider exited N" |

4. Read credentials only from `~/.config/fleet/providers/<name>.env`, which the home
   machine pushes with `fleet secrets push <name> <node>`. Never print them.

### Usage limits (exit 75)

Before it exits with `75`, the adapter writes `logs/limit.json`:

```json
{"provider": "claude", "kind": "five_hour", "resets_at": 1763499600, "message": "You've hit your limit"}
```

`resets_at` is a Unix time in seconds, or `null` when the provider did not say. The
worker writes the hold to `~/fleet/.limit` with an end time of `resets_at` plus one
minute (`LIMIT_MARGIN_SECONDS`), or one hour from now when `resets_at` is missing,
then retries. `fleet status` shows `LIMIT until <time>`; `fleet resume <node>` ends
the hold early. A job can come back like this up to 50 times (`MAX_LIMIT_WAITS`), and
those returns do not count as retries.

The worker prepares a workspace only once (it leaves a `.prepared` marker), so a job
that comes back finds the files its session already wrote. The Claude adapter also
saves the session id in `.resume-session` and continues that same session with
`claude --resume`. Earlier transcripts are kept as `logs/transcript.N.jsonl`.

## Adding another provider later

1. Copy `claude/` to `providers/<name>/` and adapt the three scripts.
2. Add `home/secrets.example/<name>.env.example` with the variables it needs.
3. On the home machine: put `<name>` in the `providers =` line of the nodes that
   should run it in `fleet.ini`, then:

   ```
   fleet provider install <name> vps3
   fleet secrets push <name> vps3
   fleet provider check <name> vps3 --smoke
   ```

4. Dispatch jobs with `"provider": "<name>"`. `fleet dispatch` only sends a job to
   nodes that list its provider.

The worker, the queue, the pull logic and the Hermes skills do not change.
