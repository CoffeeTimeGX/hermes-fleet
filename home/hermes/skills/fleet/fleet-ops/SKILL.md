---
name: fleet-ops
description: Run the 5-VPS video fleet from the home machine with the `fleet` CLI. Check health, queue Claude jobs on each channel's VPS, follow logs, cancel, retry or hand over jobs, collect finished videos and triage failures.
version: 1.5.0
metadata:
  hermes:
    tags: [fleet, vps, ssh, video, claude]
    category: fleet
    requires_toolsets: [terminal]
---

# Fleet operations

## When to use
Any request about the VPS fleet or the videos it makes: "how is the fleet", "make a
video for <channel>", "queue tomorrow's uploads", "what failed", "collect the finished
videos", "is vps3 alive", "pause vps2", "move vps2's queue to vps4", "I want to watch
the fleet".

## The fleet
- 5 Hostinger VPSs, `vps1` to `vps5`, one Hostinger account each. The inventory is
  `~/.config/fleet/fleet.ini` (`fleet list` shows it).
- Each VPS makes the videos of its own channel (`channels` in the inventory; a VPS can
  have several, and `all` means any channel that no other VPS names). Work stays on its
  channel's VPS. Only the owner decides to move it.
- Each VPS runs `fleet-worker`, which runs Claude Code sessions from its own job queue,
  `sessions` at a time (usually 1). Jobs keep running while this computer is off.
- Each VPS signs in to its own Claude account. When an account reaches its 5-hour or
  weekly usage limit, that VPS holds its queue until the limit resets, then resumes the
  interrupted session by itself. `fleet status` shows `LIMIT until <time>` meanwhile,
  and new jobs for its channel wait in its queue.
- Results come back to `~/fleet-results/<vps>/<job-id>/` with `output/` (the
  deliverables plus `SUMMARY.txt`), `logs/` and `result.json`. On Windows that is
  `%USERPROFILE%\fleet-results`.

## Procedure
1. **Look before acting.** `fleet status` prints one line per VPS. `fleet health`
   prints only problems.
2. **Queue work.** Write a job file (see "Job format") to `~/fleet-jobs/<name>.json`,
   then run `fleet dispatch ~/fleet-jobs/<name>.json`.
   - Always set `"channel"`. The job goes to that channel's VPS. If that VPS cannot
     start it now (busy, paused, at its limit), it waits there and the command warns:
     tell the owner, and do not send it elsewhere.
   - `no VPS makes videos for channel ...`: ask the owner which VPS should make that
     channel, then add it to that VPS's `channels` line (skill `fleet-provision`).
   - `channel ... is made on <vps>, and no VPS can take ...`: that VPS is unreachable,
     or Claude is not installed or has no credentials there. Tell the owner and fix it
     (see Triage). Send the job to another VPS with `--to` only if the owner says so.
   - `--to vps2` only when the owner names a VPS. `--to all` sends a copy to every VPS
     (for tests).
   - Quick one-off: `fleet dispatch --prompt "..." --channel "<channel>"`.
   - When building many jobs, check them first with `--dry-run`.
3. **Follow progress.** `fleet jobs` lists everything. `fleet jobs vps2 --state running`
   narrows it. `fleet logs vps2 <job-id>` shows the last 200 log lines. When the owner
   wants to watch the fleet at work, point them to `fleet studio`, a page they open on
   this computer (`fleet studio --tailnet` to watch from their phone).
4. **Collect.** `fleet pull` downloads every finished job not pulled yet and prints each
   summary. Report done and FAILED jobs separately, with the folder path. `MOVED` lines
   are the partial work of jobs that were handed over; the job itself runs elsewhere.
5. **Fix.** `fleet cancel <vps> <job-id>` stops a job. `fleet retry <vps> <job-id>`
   queues a fresh copy on the same VPS.
6. **Hand over, only when the owner asks.** `fleet handover <from> <to>` moves every
   queued job of `<from>` to `<to>`; add job ids to move only those. Show the owner
   `fleet handover <from> <to> --dry-run` first when they did not name the jobs.
   - Running jobs stay. To move one anyway: `fleet cancel <from> <id>`, then
     `fleet retry <from> <id> --to <to>`, with the owner's yes.
   - A job that had started on `<from>` starts over on `<to>`; what it made comes home
     with the next `fleet pull` as a `[MOVED]` line.
   - New jobs for the channel still go to the channel's VPS. For a lasting change, the
     owner changes `channels` in the inventory (skill `fleet-provision`).
7. **Maintenance.** `fleet pause <vps>` stops a VPS from starting new jobs (running jobs
   finish). `fleet resume <vps>` undoes it.

## Job format
```json
{
  "channel": "Channel name",
  "title": "Short human title",
  "prompt": "Full instructions. The session runs unattended: say exactly what to produce, and that every deliverable goes in ./output/.",
  "template": "optional template folder from vps/templates/",
  "files": [{"path": "brief.md", "content": "optional files placed in the workspace"}],
  "timeout_minutes": 180,
  "max_turns": 300,
  "model": "",
  "effort": "",
  "max_budget_usd": 5
}
```
Only `prompt` is required. Ids are generated when missing. Every field is described in
`docs/operations/job-format.md`.

## Triage
- `UNREACHABLE` in status: run `fleet ping <vps>`, then follow
  `docs/runbooks/vps-unreachable.md`.
- `claude not ok ... no credentials`: the API key or token is missing. Ask the owner to
  fill in `~/.config/fleet/secrets/<vps>/claude.env`, then run
  `fleet secrets push claude <vps>`. Never invent or request a key in chat.
- Failed with `timed out`: raise `timeout_minutes` or split the job.
- Failed with `killed (often out of memory)`: lower `sessions` for that VPS or make the
  job lighter; see `docs/runbooks/job-failures.md`.
- Failed with `provider exited 1`: read `fleet logs <vps> <id>`, and after pulling,
  `~/fleet-results/<vps>/<id>/logs/claude.stderr`.
- `LIMIT until <time>` in status, or a job in the queue with the note `usage limit`:
  nothing is broken. That Claude account hit its usage limit; the job continues after
  the reset, and new jobs for its channel wait in the same queue. Tell the owner about
  weekly limits (`fleet health` reports those) and offer
  `fleet handover <vps> <other vps>`; hand over only after their yes.
  `fleet resume <vps>` ends a hold early, for example after the owner bought extra usage.
- `stopped halfway through a handover`: the connection broke during a handover. Run
  the same `fleet handover` again; it finishes without making a second copy.
- Low disk: `fleet pull` first, then `fleet exec <vps> -- fleet-worker gc --days 2`
  (only workspaces that were already pulled are deleted).

## Pitfalls
- Never run `fleet logs -f` from a scheduled job or a messaging chat: it never exits.
- Never start the studio (`fleet studio` without `--json`): it is the owner's page and
  keeps running until stopped. To look at the fleet yourself, use `fleet status` and
  `fleet jobs`, or `fleet studio --json`, which looks once and exits.
- Do not edit files under `/home/fleet/fleet/jobs` on a VPS by hand; use the CLI.
- Never print the contents of `~/.config/fleet/secrets/` or of any Hermes `.env`, your
  own included.
- `fleet exec ... --root`, `fleet reboot` and `fleet lockdown` change a server: say what
  you will run, and ask first unless the owner already asked for exactly that.

## Verification
- After dispatch, the job shows in `fleet jobs` as `inbox` or `running`.
- After a pull, its folder exists under `~/fleet-results/` and `fleet jobs` shows it as pulled.
