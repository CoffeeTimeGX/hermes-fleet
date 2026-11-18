# Handoff for a future Claude session

This page is for the next Claude session that works on this repository, or on the
owner's fleet. It says what exists, what must not break, how to test, and what comes
next. Read [`AGENTS.md`](https://github.com/CoffeeTimeGX/hermes-fleet/blob/main/AGENTS.md)
in the repository root too: it holds the same rules in short.

## What this is

The owner makes videos for several channels with five Hostinger VPSs, `vps1` to `vps5`,
each in its own Hostinger account and each signed in to its own Claude account (a subscription token
from `claude setup-token`). Each VPS runs headless Claude Code sessions that make videos
for all of the owner's channels.

One Hermes Agent (Nous Research) on the owner's Windows PC directs the fleet. It talks
to the owner in its terminal and on Telegram, and reaches the VPSs only through the
`fleet` command, over SSH on Tailscale. There is no Hermes on the VPSs, and the VPSs
cannot reach the PC or each other.

## State

| Done | Not done yet |
| --- | --- |
| The `fleet` CLI, the VPS worker, the Claude provider, the bootstrap and lockdown scripts, the Windows and Linux/macOS installers, Hermes' `SOUL.md` and two skills | Running the installer on the owner's PC |
| Tests: unit, local end to end, and a fake Hostinger VPS over real SSH | Tailscale set-up and provisioning the five real VPSs |
| This documentation site, with runbooks | The channel templates: `CLAUDE.md` files and Claude Code skills per channel in `vps/templates/`. The owner keeps this for a later step. |
| | Optional: the Hostinger API MCP servers for Hermes |

When you help with the set-up, follow [Getting started](getting-started.md) in order. The
owner can give you their PC through Remote Control; the VPSs are reached only through
`fleet` from that PC.

## Repository map

| Path | What it is |
| --- | --- |
| `home/bin/fleet` | The CLI. One Python file, standard library only, Python 3.9+, Windows, Linux and macOS. |
| `home/install.ps1`, `home/install.sh` | The PC installers: Git (Windows), Python, Tailscale, Hermes, then `fleet init`. |
| `home/hermes/SOUL.md`, `home/hermes/skills/fleet/*/SKILL.md` | Hermes' personality and its `fleet-ops` and `fleet-provision` skills. |
| `home/fleet.ini.example`, `home/secrets.example/`, `home/hermes/env.example` | Templates with empty values. The real files live outside the repository. |
| `home/tailscale-policy.example.hujson` | The tailnet access policy: owner's devices to `tag:fleet:22`, VPSs to nothing. |
| `vps/bootstrap.sh`, `vps/lockdown.sh` | Root scripts for a fresh Ubuntu 24.04 VPS, and for closing public SSH. |
| `vps/worker/fleet-worker` | The job runner (bash), a systemd service under the `fleet` user. |
| `vps/providers/claude/` | The Claude adapter: `install.sh`, `run.sh`, `check.sh`. The contract is in `vps/providers/README.md`. |
| `vps/templates/` | Job templates (none yet). |
| `vps/systemd/`, `vps/logrotate/` | Units and log rotation the bootstrap installs. |
| `jobs/examples/` | Example jobs. |
| `tests/` | `test_fleet.py` (unit), `e2e-local.sh`, `vps-container.sh` and their helpers. |
| `docs/`, `mkdocs.yml` | This site (MkDocs Material, published to GitHub Pages by `.github/workflows/pages.yml`). |

## Rules that must hold

- **No secrets, addresses or personal details in the repository.** Not the owner's name,
  email, location or timezone either. Examples use `203.0.113.x` and empty values.
- **The CLI stays standard-library Python 3.9 and cross-platform.** Windows matters most:
  the owner's PC runs Windows, and Hermes runs commands there through Git Bash. Remote
  commands travel base64-encoded (`wrap_remote`), so quoting never depends on the local
  shell.
- **Claude runs as `fleet`, never root.** Claude Code refuses unattended mode as root,
  and the `fleet` user's only `sudo` right is its own service.
- **Running jobs survive worker restarts.** Jobs run in their own sessions (`setsid`) and
  the unit has `KillMode=process`. `fleet sync`, `fleet restart` and a bootstrap re-run
  must never kill a job.
- **Nothing unpulled is ever deleted** on a VPS. `gc` only deletes pulled workspaces.
- **The provider contract:** exit 0 success, 75 usage limit (with `logs/limit.json`),
  78 no credentials, anything else failure. The worker knows nothing else about Claude.
- **One Claude account per VPS, used openly.** Never add anything that hides the link
  between the accounts or rotates accounts to get around limits. See
  [Claude accounts](providers/claude-accounts.md).
- **The scheduled checks stay quiet when all is well.** `fleet health --changes-only` and
  `fleet pull --quiet` print nothing then; Hermes delivers only what they print.
- **Hermes asks before anything irreversible**: lockdown, rebuilds, reboots with jobs,
  deleting results, rotating credentials.

## How to test

```bash
ruff check home/bin/fleet tests/test_fleet.py
shellcheck home/install.sh vps/*.sh vps/worker/fleet-worker vps/providers/*/*.sh tests/*.sh tests/container/* tests/lib/claude-stub
python3 -m unittest discover -s tests -v       # unit tests, seconds
bash tests/e2e-local.sh                        # three fake VPSs in folders, about a minute
bash tests/vps-container.sh                    # a fake Hostinger VPS in Docker over real SSH, a few minutes
pip install -r requirements-docs.txt && mkdocs build --strict
```

The unit tests must also pass on Python 3.9 (`python:3.9-slim` in Docker works). CI runs
all of it, and the unit tests on Windows too.

The container test replaces only what a container cannot have: systemd, ufw, Tailscale,
the hostname tools and the Claude installer (`tests/container/`). Everything else is the
real bootstrap, apt included. When it fails, it prints the worker log of the fake VPS.

## Conventions

- **Docs** are plain language for a non-specialist owner: short sentences, the result
  first, no em-dashes, no jargon without an explanation. Commands are shown exactly as
  they are typed. Every page should be correct for Windows first.
- **Versions:** `VERSION` in `home/bin/fleet` and `WORKER_VERSION` in
  `vps/worker/fleet-worker` move together. Bump both when either changes.
- **Hermes skills** carry a `version` in their front matter; bump it when they change.
- **Facts about outside products** (Claude Code flags, Hermes commands, hPanel menus,
  Tailscale settings) change often. Check the official docs before relying on one, and
  update the docs when they moved.

## Facts checked in November 2026

These were checked against the official sources while building the fleet. Check again
before relying on them.

| Fact | Source |
| --- | --- |
| `claude setup-token` makes a one-year token for scripts; it needs a subscription | [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference) |
| `ANTHROPIC_API_KEY` wins over `CLAUDE_CODE_OAUTH_TOKEN` when both are set | Claude Code authentication docs |
| `--effort` takes `low`, `medium`, `high`, `xhigh`, `max` or `ultracode` (v2.1.203+) | [CLI reference](https://code.claude.com/docs/en/cli-reference) |
| `--permission-mode dontAsk` with `--allowedTools` is an exact allowlist; `-p` runs deny what needs approval | [Permission modes](https://code.claude.com/docs/en/permission-modes) |
| Subscription sign-in is for ordinary use of Claude Code; products should use API keys | [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance) |
| Hermes cron: `create`, `edit`, `list`, `pause`, `resume`, `run`, `remove`; `--no-agent --script` files live in `$HERMES_HOME/scripts/`; empty output means no message | [Hermes cron docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron) |
| `hermes update`, `hermes --version`, `hermes uninstall`, `hermes gateway install/start/restart/status` | [Hermes CLI reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands) |
| hPanel: **Web console** and **Reboot** on the VPS Overview page; **OS & Panel > Operating System** to reinstall | [Hostinger VPS dashboard](https://www.hostinger.com/support/5726606-how-to-use-vps-dashboard-in-hostinger/), [Change the OS](https://www.hostinger.com/support/4965922-how-to-change-the-operating-system-of-your-vps-at-hostinger/) |
| Tailscale: `tailscale set --auto-update` | [Update Tailscale](https://tailscale.com/docs/features/client/update) |

## Working with the owner

- The owner skims replies between other work: lead with the result, keep it short, and
  ask only what you cannot decide.
- Never ask for a secret in chat. Secrets go into files on the PC (see
  [Configuration](reference/config.md#secrets)) that the owner fills in.
- Before anything that cannot be undone on a server, say what you will run and wait for
  a yes.
