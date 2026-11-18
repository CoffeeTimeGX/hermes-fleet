---
name: fleet-ops
description: Run the 5-VPS video fleet from the home machine with the `fleet` CLI. Check health, queue Claude jobs, follow logs, cancel or retry jobs, collect finished videos and triage failures.
version: 1.3.0
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
videos", "is vps3 alive", "pause vps2".

## The fleet
- 5 Hostinger VPSs, `vps1` to `vps5`, one Hostinger account each. The inventory is
  `~/.config/fleet/fleet.ini` (`fleet list` shows it).
- Each VPS runs `fleet-worker`, which runs Claude Code sessions from its own job queue,
  `sessions` at a time (usually 1). Jobs keep running while this computer is off.
- Each VPS signs in to its own Claude account. When an account reaches its 5-hour or
  weekly usage limit, that VPS holds its queue until the limit resets, then resumes the
  interrupted session by itself. `fleet status` shows `LIMIT until <time>` meanwhile.
- Results come back to `~/fleet-results/<vps>/<job-id>/` with `output/` (the
  deliverables plus `SUMMARY.txt`), `logs/` and `result.json`. On Windows that is
  `%USERPROFILE%\fleet-results`.

## Procedure
1. **Look before acting.** `fleet status` prints one line per VPS. `fleet health`
   prints only problems.
2. **Queue work.** Write a job file (see "Job format") to `~/fleet-jobs/<name>.json`,
   then run `fleet dispatch ~/fleet-jobs/<name>.json`.
   - The least busy VPS is picked automatically. Force one with `--to vps2`, or send a
     copy to every VPS with `--to all`.
   - Quick one-off: `fleet dispatch --prompt "..." --channel "<channel>"`.
   - When building many jobs, check them first with `--dry-run`.
3. **Follow progress.** `fleet jobs` lists everything. `fleet jobs vps2 --state running`
   narrows it. `fleet logs vps2 <job-id>` shows the last 200 log lines.
4. **Collect.** `fleet pull` downloads every finished job not pulled yet and prints each
   summary. Report done and FAILED jobs separately, with the folder path.
5. **Fix.** `fleet cancel <vps> <job-id>` stops a job. `fleet retry <vps> <job-id>`
   queues a fresh copy (add `--to auto` to let another VPS take it).
6. **Maintenance.** `fleet pause <vps>` stops a VPS from starting new jobs (running jobs
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
  the reset, and `fleet dispatch` sends new work to other VPSs meanwhile. Tell the owner
  only about weekly limits (`fleet health` reports those). `fleet resume <vps>` ends a
  hold early, for example after the owner bought extra usage.
- Low disk: `fleet pull` first, then `fleet exec <vps> -- fleet-worker gc --days 2`
  (only workspaces that were already pulled are deleted).

## Pitfalls
- Never run `fleet logs -f` from a scheduled job or a messaging chat: it never exits.
- Do not edit files under `/home/fleet/fleet/jobs` on a VPS by hand; use the CLI.
- Never print the contents of `~/.config/fleet/secrets/` or of Hermes' `.env`.
- `fleet exec ... --root`, `fleet reboot` and `fleet lockdown` change a server: say what
  you will run, and ask first unless the owner already asked for exactly that.

## Verification
- After dispatch, the job shows in `fleet jobs` as `inbox` or `running`.
- After a pull, its folder exists under `~/fleet-results/` and `fleet jobs` shows it as pulled.
