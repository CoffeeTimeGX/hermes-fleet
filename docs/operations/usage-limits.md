# Usage limits

A Claude Pro or Max subscription has usage limits: one that resets 5 hours after a
session starts, and weekly limits. A VPS that runs Claude around the clock will reach
them. The fleet handles that for you: the VPS stops at the limit, waits for the reset,
and then finishes the interrupted job where it stopped.

With a Console API key there are no 5-hour or weekly limits, only rate limits, so
nothing on this page happens. See [Claude accounts](../providers/claude-accounts.md).

## What happens, step by step

1. **Short limits are ridden out.** Claude Code itself waits and retries when it gets a
   brief rate limit or an "overloaded" answer, for up to 15 minutes.
2. **The session stops at the usage limit.** The Claude adapter on the VPS recognises
   it, notes when the limit resets, and remembers the Claude session.
3. **The job goes back to the front of the queue**, with the note
   `usage limit: ... continues after <time>`. It does not count as a failed attempt.
4. **The VPS holds its queue.** It starts no job at all until one minute after the
   reset. Jobs that are already running on a VPS with several sessions carry on.
5. **Your other VPSs take the new work.** `fleet dispatch` skips a VPS that waits for
   its limit, as long as another VPS can start the job. If every VPS waits, it queues the
   job on the one whose limit ends first.
6. **After the reset, the job continues.** The VPS starts it again, and the adapter
   resumes the same Claude session (`claude --resume`) with the instruction to check
   what it already made and finish the rest. The files from before the limit are still
   in the workspace.

If Claude Code no longer has the interrupted session (it keeps them for 14 days), the
job starts over in the same workspace, with its earlier files still there.

If the limit gives no reset time, the VPS tries again after an hour. A job that keeps
hitting the limit is given up after 50 waits and filed as failed.

## What you see

`fleet status`:

```
NODE  SERVICE                   QUEUED  RUNNING  DONE  FAILED  UNPULLED  DISK FREE      LOAD  PROVIDERS
vps3  active LIMIT until 17:05  1       0/1      14    0       0         70.2 GB (73%)  0.04  claude:ok
```

The time is your PC's local time, with the day added when the reset is not today.

`fleet jobs`:

```
NODE  STATE  ID                             CHANNEL  STARTED               FINISHED  NOTE
vps3  inbox  20261118-120544-history-q81mz  History  2026-11-18T12:05:49Z  -         usage limit: You've hit your limit; continues after 2026-11-18T17:05:00Z
```

**Telegram.** The 5-hour limit is routine, so the health check stays quiet about it. It
messages you only about a wait longer than 6 hours, which means a weekly limit:

```
Fleet health: 1 open problem(s)
NEW  vps3: claude usage limit reached (You've hit your weekly limit); its queue waits until Fri 20 Nov 09:00 and then continues by itself (fleet dispatch sends new jobs to other VPSs meanwhile)
```

When the wait ends, you get a `Resolved` message.

## End a wait early

```
fleet resume vps3
```

Use it when the limit no longer applies, for example after you moved that VPS to an
API key or added extra usage to the Claude account. If the limit is in fact still
there, the next job meets it again and the wait comes back by itself.

## Make the limits hurt less

- **Spread the work.** Leave the choice of VPS to `fleet dispatch`. Five accounts with a
  share each go further than one account doing everything.
- **Watch the heavy settings.** Higher `effort` levels and bigger models use up a limit
  faster. Keep them for the jobs that need them (see [Job format](job-format.md)).
- **Split long jobs.** A job that stops at a limit continues later, but several shorter
  jobs spread more evenly over the five accounts.
- **Move a busy VPS to an API key** when one account is not enough. See
  [Switch a VPS to an API key](../providers/claude-accounts.md#switch-a-vps-to-an-api-key).

Do not try to get around the limits with extra accounts or by switching accounts on one
VPS. One account per VPS, used openly, is what keeps the fleet within Anthropic's rules.

## Settings

Two worker settings control the waiting. Put them in `/etc/fleet/worker.local.env` on
the VPS and restart the worker (see [Worker reference](../reference/worker.md#settings)):

| Setting | Default | Meaning |
| --- | --- | --- |
| `LIMIT_MARGIN_SECONDS` | `60` | How long after the reset time the VPS waits before it starts jobs again. |
| `MAX_LIMIT_WAITS` | `50` | After this many waits, the job is filed as failed. |

Other providers get the same handling when their adapter follows the contract: exit
code 75 and a `logs/limit.json` with the reset time. See
[Add another provider](../providers/adding-a-provider.md).
