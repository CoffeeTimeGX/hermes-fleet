# Runbooks

Step-by-step fixes for the things that go wrong. Hermes follows the same pages, so you
can also just tell it what you see: *"vps4 is unreachable, follow the runbook"*.

## Start here

Whatever the problem, these three commands show where it is:

```
fleet health          # every problem, each with its fix
fleet status          # one line per VPS
fleet ping            # can your PC reach each VPS at all?
```

## Find the right page

| What you see | Runbook |
| --- | --- |
| `unreachable` in `fleet health`, `UNREACHABLE` in `fleet status`, or `fleet ping` fails | [VPS unreachable](vps-unreachable.md) |
| A job `failed`, with a reason such as `timed out`, `killed` or `provider exited 1` | [Job failures](job-failures.md) |
| `low disk` in `fleet health` | [Disk full](disk-full.md) |
| `claude not ok`, a token about to expire, or a key that leaked | [Rotate credentials](rotate-credentials.md) |
| A VPS is broken beyond repair, or you want to start it clean | [Rebuild a VPS](rebuild-vps.md) |
| `LIMIT until ...` in `fleet status` | Nothing is broken: [Usage limits](../operations/usage-limits.md) |
| `fleet-worker service is ...` or `the worker loop is not running` | `fleet restart <vps>`, then `fleet status <vps>` |
| `worker returned no status (run fleet sync)` | `fleet sync <vps>` |
| `security updates need a reboot` | `fleet reboot <vps>` when no job runs |
| Public SSH closed and Tailscale broken on a VPS | [Close public SSH: locked out](../vps/lockdown.md#locked-out) |

## Good habits

- **Look before changing.** Read `fleet health` and the job's reason first. Most
  problems say what fixes them.
- **One VPS at a time.** Fix and check one VPS before you touch the next. The others
  keep working meanwhile, and `fleet dispatch` sends new jobs around a broken one.
- **Pause what you work on.** `fleet pause vps3` stops new jobs from starting there
  while you repair it. `fleet resume vps3` when you are done.
- **Nothing on a VPS is precious until it is pulled.** Run `fleet pull` before anything
  that could lose data, such as a rebuild.
