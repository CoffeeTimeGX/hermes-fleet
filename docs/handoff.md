# Handoff for a future Claude session

This page is for the next Claude session that works on this repository, or on the
owner's fleet. It says what exists, what must not break, how to test, and what comes
next. Read [`AGENTS.md`](https://github.com/CoffeeTimeGX/hermes-fleet/blob/main/AGENTS.md)
in the repository root too: it holds the same rules in short.

## What this is

The owner makes videos for several channels with five Hostinger VPSs, `vps1` to `vps5`,
each in its own Hostinger account and each signed in to its own Claude account (a
subscription token from `claude setup-token`). Each VPS runs headless Claude Code
sessions that make the videos of its own channel (`channels` in `fleet.ini`).

One Hermes Agent (Nous Research) on the owner's Windows PC directs the fleet, from its
own Hermes profile named `director` (`hermes -p director`). It runs on a model from a
provider the owner picks with `hermes -p director model`, not on Claude. It talks to the
owner in its terminal and on Telegram, and reaches the VPSs only through the `fleet`
command, over SSH on Tailscale. There is no Hermes on the VPSs, and the VPSs cannot
reach the PC or each other.

## State

| Done | Not done yet |
| --- | --- |
| The `fleet` CLI, the VPS worker, the Claude provider, the bootstrap and lockdown scripts, the Windows and Linux/macOS installers, Hermes' `SOUL.md` and two skills | Running the installer on the owner's PC |
| Tests: unit, local end to end, and a fake Hostinger VPS over real SSH | Tailscale set-up and provisioning the five real VPSs |
| This documentation site, with runbooks | The channel templates: `CLAUDE.md` files and Claude Code skills per channel in `vps/templates/`. The owner keeps this for a later step. |
| The studio (`fleet studio`): a page on the owner's PC that shows every VPS at work, from above | Optional: the Hostinger API MCP servers for Hermes |
| The video check, the daily report, the week plan, publishing to YouTube, TikTok and Instagram, the work schedule of each VPS, and the owner's ideas list (`fleet ideas`) | The owner's own apps on Google Cloud, TikTok for Developers and Meta, and TikTok's app review ([Publishing](operations/publishing.md)) |
| The trend looker (`fleet trends`), the zeppelin over the lot: on the PC beside Hermes, it looks at what rises on YouTube in each channel's niche; Hermes pitches a video and "go 3" queues it first on the channel's VPS | The owner's YouTube Data API key (`fleet trends key`, [Trend looker](operations/trends.md)) |
| | The other ideas on the owner's list (`fleet ideas`). The starter list is `STARTER_IDEAS` in `home/bin/fleet`. |

When you help with the set-up, follow [Getting started](getting-started.md) in order. The
owner can give you their PC through Remote Control; the VPSs are reached only through
`fleet` from that PC.

## Repository map

| Path | What it is |
| --- | --- |
| `home/bin/fleet` | The CLI. One Python file, standard library only, Python 3.9+, Windows, Linux and macOS. |
| `home/studio/studio.html` | The studio board, a page fragment. `fleet studio` serves it in a full page from the PC with live data. Opened as a plain file, it shows an example lot. It has a strip of the last 24 hours that replays the board, and a screening room for the collected videos. |
| `home/studio/pixel.html` | The pixel lot: the same fleet drawn on a canvas in isometric pixel art, every character on the lot tied to a real value, in a town that is only scenery. The light follows the viewer's clock minute by minute, the season follows the date and the weather is made up from the date and the hour (scenery too). The picture zooms in sharp steps and drags, and full screen keeps the screen on. Sound, off until turned on, is made in the page with Web Audio. A screen on the lawn shows the collected videos, the pitch room before stage 1 reads out the owner's ideas list, the zeppelin over the lot is the trend looker, and Replay plays back the last 24 hours. One file with no build step, served as `/pixel.html`. |
| `home/studio/studio-data.js` | What both views share: the example lot, the polling of `/api/studio`, the meaning of each state, the replay (`at()` rebuilds a past moment from the job times, `setNow()` moves the shared clock), the 24-hour strip and the video player. `fleet studio` serves it with `FLEET_STUDIO_LIVE` set, and serves collected videos under `/media/<vps>/<job>/<file>` from each job's `output` folder in `results_dir`. |
| `home/install.ps1`, `home/install.sh` | The PC installers: Git (Windows), Python, Tailscale, Hermes, then `fleet init`. |
| `home/hermes/SOUL.md`, `home/hermes/skills/fleet/*/SKILL.md` | Hermes' personality and its `fleet-ops` and `fleet-provision` skills. |
| `home/fleet.ini.example`, `home/secrets.example/`, `home/hermes/env.example` | Templates with empty values. The real files live outside the repository. |
| `home/tailscale-policy.example.hujson` | The tailnet access policy: owner's devices to `tag:fleet:22`, VPSs to nothing. |
| `vps/bootstrap.sh`, `vps/lockdown.sh` | Root scripts for a fresh Ubuntu 24.04 VPS, and for closing public SSH. |
| `vps/worker/fleet-worker` | The job runner (bash), a systemd service under the `fleet` user. |
| `vps/worker/fleet-check` | The video check after each job (Python, standard library, uses `ffprobe` and `ffmpeg`). It never fails a job. |
| `vps/worker/fleet-schedule` | The work schedule (Python, standard library): reads `schedule.json` on the VPS and tells the worker when it may start a job. |
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
- **Hermes does not run on Claude.** The owner picks its provider and model with
  `hermes -p director model`. `fleet init` never sets them, and the docs never point
  Hermes at a Claude model.
- **Hermes works from its `director` profile.** `fleet init` creates it and every Hermes
  command the fleet runs has `-p director`, so the fleet's settings, Telegram bot and
  scheduled jobs stay apart from the owner's default Hermes. The one gateway (started
  from the default profile, `hermes gateway install`) serves it.
- **One channel per VPS, and work never moves by itself.** `fleet dispatch` sends a job
  only to the VPS whose `channels` names its channel, and the job waits there when that
  VPS is busy, paused or at its limit. Work moves to another VPS only when the owner
  asks: `fleet handover`, `--to` or `fleet retry --to`. Hermes offers a handover, and
  never does one on its own.
- **One Claude account per VPS, used openly.** Never add anything that hides the link
  between the accounts or rotates accounts to get around limits. See
  [Claude accounts](providers/claude-accounts.md).
- **The studio only reads.** `fleet studio` listens on `127.0.0.1`, or on the PC's
  Tailscale address with `--tailnet`, answers only requests addressed to those names,
  and has nothing that changes the fleet. Actions go through `fleet` commands and the
  director. On the pixel lot, only the lot stands for the fleet: the town around it,
  its traffic and its passers-by stand for nothing.
- **The scheduled checks stay quiet when all is well.** `fleet health --changes-only` and
  `fleet pull --quiet` print nothing then; Hermes delivers only what they print.
- **Hermes asks before anything irreversible**: lockdown, rebuilds, reboots with jobs,
  deleting results, rotating credentials.
- **The schedule trumps everything, on the VPS.** No job starts outside a VPS's work
  schedule, whoever queued it; `fleet resume` does not override it, only
  `fleet schedule open` does. Running jobs always finish. A `schedule.json` that cannot
  be read starts nothing. Off duty never moves work to another VPS. Random start times
  only spread the work through the day.
- **Only the owner approves.** Week plan topics stay drafts until the owner says yes;
  Hermes never approves one, never changes a schedule and never posts to Instagram
  (public at once) unless the owner asks. YouTube uploads are private and TikTok uploads
  wait in the owner's inbox.
- **Publishing uses the platforms' official APIs only**, with the owner's own apps and
  accounts. The sign-ins stay in `secrets/publish/` on the PC and never reach a VPS.

## How to test

```bash
ruff check home/bin/fleet tests/test_fleet.py vps/worker/fleet-check vps/worker/fleet-schedule
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
| `hermes model` picks Hermes' provider and model (`model.provider`, `model.default`); Nous Portal, OpenRouter, OpenAI, Gemini and many more are supported; agent use needs at least 64K tokens of context | [Hermes providers](https://hermes-agent.nousresearch.com/docs/integrations/providers) |
| Hermes profiles are separate Hermes homes (`~/.hermes/profiles/<name>/`) with their own config, `.env`, `SOUL.md`, memory, skills and cron jobs; `hermes -p <name>` runs one; `hermes profile create/list/show/delete`; by default one gateway, installed from the default profile, serves every profile; a bot token works in one profile only (a second one is parked as `duplicate_credential`); clones never copy bot tokens or cron jobs | [Hermes profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles), [Many gateways](https://hermes-agent.nousresearch.com/docs/user-guide/multi-profile-gateways) |
| Claude Code Projects (claude.ai/code and the Claude apps) are in public beta on Pro and Max, and are not used from the terminal or `claude -p` | [Claude Code projects](https://code.claude.com/docs/en/claude-projects.md) |
| YouTube: uploads from unverified API projects are not restricted to private; 100 upload calls a day; a Google app in Testing loses its sign-ins after 7 days | [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert), [Manage App Audience](https://support.google.com/cloud/answer/15549945) |
| TikTok: the app must be approved for `video.upload`; at most 5 pending inbox shares in 24 hours; the user finishes the post in the app; desktop sign-in uses a hex SHA-256 code challenge and a `127.0.0.1` redirect with a port; app review takes days to two weeks and wants a demo video | [Login Kit for Desktop](https://developers.tiktok.com/docs/en/login-kit-desktop), [Create an app](https://developers.tiktok.com/docs/en/getting-started-create-an-app) |
| Instagram: Reels through `media` (REELS) then `media_publish`; the video must be on a public server; 100 API posts per 24 hours; dashboard tokens last 60 days; the account must be professional | [Content publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/), [Instagram API with Instagram Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started) |
| Tailscale Funnel serves on ports 443, 8443 and 10000; the macOS App Store and standalone apps cannot share files | [Tailscale Funnel](https://tailscale.com/kb/1223/funnel) |

## Working with the owner

- The owner skims replies between other work: lead with the result, keep it short, and
  ask only what you cannot decide.
- Never ask for a secret in chat. Secrets go into files on the PC (see
  [Configuration](reference/config.md#secrets)) that the owner fills in.
- Before anything that cannot be undone on a server, say what you will run and wait for
  a yes.
