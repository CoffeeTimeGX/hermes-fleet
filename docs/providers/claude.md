# Claude Code on the VPSs

Every job on every VPS is one headless [Claude Code](https://code.claude.com/docs)
session. This page explains how it is installed, signed in and run. The code is in
[`vps/providers/claude/`](https://github.com/CoffeeTimeGX/hermes-fleet/tree/main/vps/providers/claude).

## How a session runs

For each job, the worker calls `run.sh`, which runs Claude Code as the `fleet` user,
inside the job's workspace, roughly like this:

```
claude -p "<the job's prompt>" \
  --output-format stream-json --verbose \
  --append-system-prompt "<the fleet note>" \
  --permission-mode bypassPermissions \
  [--max-turns N] [--model M] [--effort E] [--max-budget-usd B] [--allowedTools T]
```

- **The fleet note** tells the session that it runs unattended on a fleet VPS, which
  channel and job it works for, that every deliverable goes in `./output/`, and that its
  final message becomes `output/SUMMARY.txt`. It also names the
  [skills the VPS has](skills.md), such as `lumina-sfx` for sound effects.
- **Permissions.** Nobody is there to approve each command, so sessions run with
  `bypassPermissions` by default. What keeps that safe is where they run: an
  unprivileged user, a workspace of their own, and a VPS that holds no secret other
  than its own Claude credential. A job can ask for less: `"permission_mode": "dontAsk"`
  with an `allowed_tools` list lets the session use only those tools, and denies
  everything else. See [Job format](../operations/job-format.md#permissions).
- **Short hiccups.** Claude Code retries brief rate limits and overloaded-server errors
  by itself for up to 15 minutes (`CLAUDE_CODE_RETRY_WATCHDOG`). Longer usage limits are
  handled by the fleet: see [Usage limits](../operations/usage-limits.md).
- **Very long prompts** (over 100,000 characters) are written to `JOB_PROMPT.md` in the
  workspace, and the session is told to read it.

## What a finished job contains

| File | What it is |
| --- | --- |
| `output/` | The deliverables, plus `SUMMARY.txt` (the session's final message). |
| `result.json` | Claude Code's final result: success or error, number of turns, duration, cost estimate, session id. |
| `logs/provider.log` | One line per attempt: Claude Code version, sign-in type, mode, model, and how it ended. |
| `logs/transcript.jsonl` | Everything the session did, as Claude Code's streaming JSON. Earlier attempts are kept as `transcript.1.jsonl`, `transcript.2.jsonl` and so on. |
| `logs/claude.stderr` | Claude Code's error output. |

## Install and update

```
fleet provider install claude all                      # the stable release channel
fleet provider install claude all --version latest     # the newest release
fleet provider install claude all --version 2.1.300    # one exact version
fleet provider check claude all                        # quick check, spends nothing
fleet provider check claude all --smoke                # also runs a one-turn session
```

The install uses Anthropic's native installer (no Node.js needed) and puts `claude` in
the `fleet` user's `~/.local/bin`. It also writes the fleet's Claude Code settings to
`~/.claude/settings.json` on the VPS:

- Claude Code's own auto-updater is **off**, so all five VPSs stay on the version you
  chose and change only when you run `fleet provider install` again.
- Session transcripts are kept for 14 days. A session interrupted by a usage limit can
  only be resumed while its transcript exists, and even a weekly limit resets sooner.

Claude Code refuses to run unattended as root, which is one more reason everything runs
as `fleet`.

`fleet provider install claude` also installs the [skills every VPS has](skills.md).

## Credentials

On the VPS, the credential lives in `~/.config/fleet/providers/claude.env`, readable only
by the `fleet` user. It comes from `~/.config/fleet/secrets/<vps>/claude.env` on your PC,
through `fleet secrets push claude <vps>`. The file holds one of:

| Variable | What it is |
| --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | **The fleet's default.** A one-year token from `claude setup-token`, tied to a Claude Pro or Max subscription. One Claude account per VPS. |
| `ANTHROPIC_API_KEY` | A Claude Console API key, billed per use, with no 5-hour or weekly limits. |

If both are set, Claude Code uses the API key. Which to choose, and Anthropic's rules
about it, are on [Claude accounts and Anthropic's rules](claude-accounts.md).

Optional defaults for every job on a VPS can go in the same file: `ANTHROPIC_MODEL`,
`CLAUDE_MAX_TURNS` and `CLAUDE_PERMISSION_MODE`. A job's own fields win.

`fleet health` warns when a subscription token was pushed more than 330 days ago, a
month before it expires. See [Rotate credentials](../runbooks/rotate-credentials.md).
