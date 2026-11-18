# Disk full

**Symptoms:** `fleet health` says `vps2: low disk, 4.1 GB free (4%)`, maybe followed by
`new jobs are on hold`.

**What the fleet does by itself:** under 3 GB free, the VPS starts no new jobs, so a
render does not fail halfway for lack of space. Running jobs continue. As soon as there
is room again, it starts the queue by itself, within seconds.

## 1. Pull, then clean up

Most of the space is finished jobs. A job's workspace stays on the VPS until your PC has
pulled it, plus 7 days. So first, pull:

```
fleet pull vps2
```

Then delete the workspaces that were pulled more than a day ago:

```
fleet exec vps2 -- fleet-worker gc --days 0
```

```
--- vps2 (exit 0)
removed 23 pulled workspace(s) older than 0 day(s)
```

`gc` only deletes workspaces your PC already has. Nothing unpulled is ever deleted.

## 2. Find what else takes space

```
fleet exec vps2 -- "du -sh /home/fleet/fleet/work/* 2>/dev/null | sort -h | tail -n 10"
fleet exec vps2 -- "du -sh ~/.claude ~/.cache ~/.local/share 2>/dev/null"
fleet exec vps2 --root -- "df -h / && du -xsh /var/log /var/cache/apt /tmp 2>/dev/null"
```

| What is big | What to do |
| --- | --- |
| Workspaces of jobs that are not pulled yet | Check why: is the job still running, or did the pull fail? Run `fleet pull vps2` and read its errors. |
| One huge workspace | A session that downloaded or rendered too much. Pull the job, then ask Hermes to adjust the prompt. |
| `~/.cache` | Caches of tools the sessions installed (pip, for example). Safe to empty: `fleet exec vps2 -- rm -rf ~/.cache` |
| `~/.claude` | Claude Code's session records, kept 14 days for resuming after usage limits. Leave it unless it is huge. |
| `/var/cache/apt` | Downloaded packages: `fleet exec vps2 --root -- apt-get clean` |

## 3. If it keeps filling up

- Keep fewer days of pulled workspaces: add `GC_DAYS=2` to `/etc/fleet/worker.local.env`
  on the VPS (see [Worker reference](../reference/worker.md#settings)).
- Ask the sessions to clean up their own temporary files in the prompt or in the
  channel's template, and to keep only the deliverables in `output/`.
- Give the VPS a bigger disk: upgrade its plan in hPanel.

## Check

```
fleet status vps2
fleet health
```

`fleet health` sends a `Resolved` message when the space is back.

## On your PC

The fleet never deletes anything on your PC. If `fleet pull` fails because your own disk
is full, move old folders out of `fleet-results` (see
[Results](../operations/results.md#space-on-your-pc)), or point `results_dir` at a bigger
disk.
