# Instructions for coding agents

Hermes Fleet: a Hermes Agent on the owner's home PC directs five Hostinger VPSs that run
headless Claude Code sessions to make videos, one channel per VPS. The PC side is `home/`
(the `fleet` CLI, installers, Hermes' `SOUL.md` and skills); the VPS side is `vps/`
(bootstrap, lockdown, the `fleet-worker` job runner, provider adapters). Read
`docs/handoff.md` for the full picture before a larger change.

## Commands

```bash
ruff check home/bin/fleet tests/test_fleet.py vps/worker/fleet-check vps/worker/fleet-schedule
shellcheck home/install.sh vps/*.sh vps/worker/fleet-worker vps/providers/*/*.sh vps/skills/*.sh tests/*.sh tests/container/* tests/lib/claude-stub
python3 -m unittest discover -s tests -v      # must pass on Python 3.9 and on Windows too
bash tests/e2e-local.sh                       # local end to end, no network
bash tests/skills-local.sh                    # the VPS skills installer, no network
bash tests/vps-container.sh                   # fake Hostinger VPS in Docker over real SSH (slow)
mkdocs build --strict                         # after pip install -r requirements-docs.txt
```

Run the unit tests, the e2e test and shellcheck/ruff for any code change, and
`mkdocs build --strict` for any docs change. Run the container test when the bootstrap,
lockdown, worker, provider scripts or the CLI's SSH paths change.

## Rules

- Never commit secrets, real addresses or personal details (names, emails, locations,
  timezones). Examples use `203.0.113.x` and empty values.
- `home/bin/fleet` stays one standard-library Python file that runs on Python 3.9+ on
  Windows, Linux and macOS. Windows is the owner's platform: test quoting and paths
  with it in mind.
- Claude Code runs as the unprivileged `fleet` user, never as root.
- Running jobs must survive `fleet sync`, `fleet restart` and bootstrap re-runs.
- Nothing unpulled is ever deleted on a VPS.
- Provider adapters follow `vps/providers/README.md`: exit 0, 75 (usage limit, with
  `logs/limit.json`), 78 (no credentials), anything else is a failure.
- Hermes runs on a model the owner picks with `hermes -p director model`, never on Claude:
  `fleet init` does not set Hermes' model. Every Hermes command the fleet runs targets the
  `director` profile (`hermes -p director`).
- Each VPS makes the videos of its own channels (`channels` in `fleet.ini`). Work moves to
  another VPS only when the owner asks: `fleet handover`, `--to` or `fleet retry --to`.
  `fleet trends shift` is the owner's answer too: today's planned videos keep their VPS
  and time and take the trend's topic. Nothing moves work automatically.
- The skills every VPS has are listed in `vps/skills/skills.json`, each pinned to a tag and
  its full commit; Node.js is pinned with its checksums. `fleet skills install` installs
  them for the `fleet` user only, never as root, and never replaces a skill folder the
  fleet did not install.
- One Claude account per VPS, used openly. Do not add anything that hides the link
  between accounts or switches accounts to get around usage limits.
- Bump `VERSION` in `home/bin/fleet` and `WORKER_VERSION` in `vps/worker/fleet-worker`
  together, and a skill's `version` when the skill changes.

## Docs style

Plain language for a non-specialist: short sentences, the result first, commands exactly
as typed, Windows first. No em-dashes. Facts about Claude Code, Hermes, Hostinger and
Tailscale change: check the official docs before you rely on one.
