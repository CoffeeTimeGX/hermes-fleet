# Configuration

Everything that is specific to your fleet lives on your PC, outside the repository, so
the repository stays public and the same for everyone. `fleet init` creates these files
once and never overwrites them.

| File on your PC | What it holds |
| --- | --- |
| `~/.config/fleet/fleet.ini` | The inventory: your VPSs and the fleet's settings. |
| `~/.config/fleet/secrets/` | Credentials for the VPSs: Claude, Tailscale. |
| `~/.ssh/fleet_ed25519` and `.pub` | The fleet SSH key. |
| `~/.ssh/config.d/fleet` | SSH settings, so `ssh vps1` works. |
| The director's folder in Hermes | The director's settings, its `.env` with its own secrets, `SOUL.md`, scripts. |
| `~/.config/fleet/state/health.json` | What the scheduled health check last reported. |

On Windows, `~` is your user folder, `C:\Users\<you>`.

## fleet.ini

The inventory. It has a `[defaults]` section and one section per VPS:

```ini
[defaults]
user = fleet
remote_root = /home/fleet/fleet
results_dir = ~/fleet-results
secrets_dir = ~/.config/fleet/secrets
ssh_key = ~/.ssh/fleet_ed25519
connect_timeout = 10

[vps1]
host = vps1
public_ip = 203.0.113.10
hostinger_account = hostinger-account-1
providers = claude
sessions = 1
channels = Space Facts
enabled = true
```

**`[defaults]`**

| Key | Default | Meaning |
| --- | --- | --- |
| `results_dir` | `~/fleet-results` | Where `fleet pull` puts finished jobs. Any folder, an external disk included. |
| `secrets_dir` | `~/.config/fleet/secrets` | Where the credentials for the VPSs are. |
| `ssh_key` | `~/.ssh/fleet_ed25519` | The private key `fleet` logs in with. |
| `connect_timeout` | `10` | Seconds to wait for a VPS to answer. |
| `user` | `fleet` | The user `fleet` logs in as. Leave it. |
| `remote_root` | `/home/fleet/fleet` | The fleet's folder on each VPS. The bootstrap creates this one; leave it. |

**One section per VPS.** The section name is the VPS's name in the fleet: lowercase
letters, digits and dashes, such as `vps1`.

| Key | Default | Meaning |
| --- | --- | --- |
| `host` | the section name | How your PC reaches the VPS. With Tailscale's MagicDNS, the name itself; a `100.x.y.z` Tailscale address also works. |
| `public_ip` | empty | The VPS's public address, from hPanel. Only `fleet bootstrap --public` uses it. |
| `port` | `22` | The SSH port. |
| `hostinger_account` | empty | A label to remember which Hostinger account owns the VPS. |
| `providers` | `claude` | The tools this VPS runs, comma-separated. `fleet dispatch` only sends a job to VPSs that list its provider. |
| `sessions` | `1` | How many jobs run at the same time. After a change, run `fleet bootstrap <vps> --skip-upgrade`. |
| `channels` | `all` when the line is missing | The channels this VPS makes videos for, comma-separated, such as `Space Facts, History`. `fleet dispatch` sends a channel's jobs only to the VPS that names it (capitals, spaces and `-` do not matter), and they wait there when it is busy, paused or at its usage limit. When several VPSs name a channel, the least busy one gets each job. `all` takes every channel that no other VPS names. Empty: only jobs sent to it with `--to`. Work moves to another VPS only with `fleet handover` or `--to`. |
| `enabled` | `true` | `false` takes the VPS out of `all` and out of dispatching, without deleting anything. Commands that name it still work. |

Text after `;` or `#` is a comment.

### Add a sixth VPS

1. Add a `[vps6]` section, copied from another one, with the new public IP and the
   channel it makes videos for.
2. Run `fleet init` again: it creates `secrets/vps6/claude.env` and leaves everything
   else as it is.
3. Create the VPS and provision it as for the first five: [Create the VPSs](../vps/hostinger.md),
   then [Provision a VPS](../vps/provisioning.md).

## Secrets

The secrets folder holds one folder per VPS, plus the files all VPSs share:

```
~/.config/fleet/secrets/
  vps1/claude.env            vps1's Claude token or API key
  vps2/claude.env
  ...
  tailscale.env              the Tailscale auth key for the bootstrap
```

`fleet secrets push claude vps1` reads `secrets/vps1/claude.env`. When a VPS has no file
of its own, it falls back to `secrets/claude.env`. Do not use that shared file for
subscription tokens: each VPS has its own Claude account.

**`claude.env`**

| Variable | Meaning |
| --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | A subscription token from `claude setup-token`. The fleet's default. |
| `ANTHROPIC_API_KEY` | A Console API key. When both are set, Claude Code uses this one. |
| `ANTHROPIC_MODEL` | Optional: the model for jobs that do not name one. |
| `CLAUDE_MAX_TURNS` | Optional: `max_turns` for jobs that do not set it. |
| `CLAUDE_PERMISSION_MODE` | Optional: `permission_mode` for jobs that do not set it. |

**`tailscale.env`**: `TS_AUTHKEY`, the auth key `fleet bootstrap` joins new VPSs with. A
VPS can have its own in `secrets/<vps>/tailscale.env`.

**The file format:** one `NAME=value` per line, `#` for comments. Quotes around a value
and `export ` before a name are allowed. Empty values are not pushed.

**Who can read them:** on Linux and macOS, `fleet` refuses a secrets file that other
users can read; fix it with `chmod 600 <file>`. On Windows, `fleet init` limits the
secrets folder to your user (and the system).

## On each VPS

| File | What it holds |
| --- | --- |
| `/etc/fleet/worker.env` | The worker's settings, written by the bootstrap. |
| `/etc/fleet/worker.local.env` | Your own worker settings, which win. See [Worker settings](worker.md#settings). |
| `/home/fleet/.config/fleet/providers/claude.env` | The Claude credential, from `fleet secrets push`. Readable only by `fleet`. |
| `/home/fleet/.claude/settings.json` | Claude Code's settings for the sessions. |

`fleet provider install claude` sets three things in Claude Code's `settings.json` and
leaves any other setting you add there alone:

| Setting | Value | Why |
| --- | --- | --- |
| `env.DISABLE_AUTOUPDATER` | `"1"` | All VPSs stay on the version you installed. |
| `autoUpdatesChannel` | `stable` or `latest` | The channel you installed from. |
| `cleanupPeriodDays` | `14` (unless already set) | Session records are kept 14 days, so a session interrupted by a usage limit can be resumed. |

## Hermes

Hermes keeps its files in `%LOCALAPPDATA%\hermes` on Windows and `~/.hermes` on Linux and
macOS. The director is a Hermes profile with a folder of its own in there,
`profiles/director` (`hermes profile show director` prints the full path). Everything
below is in the director's folder: your default Hermes is left alone.

`fleet init` creates the profile when it is missing, then applies the director's
settings with `hermes -p director config set`, after a backup of `config.yaml`
(`config.yaml.bak-<date>`). Lists are extended, never replaced. It leaves the model
alone: you choose the director's provider and model with `hermes -p director model`,
which sets `model.provider` and `model.default`.

| Setting | Value | Why |
| --- | --- | --- |
| `terminal.cwd` | the repository folder | Hermes runs `fleet` and reads the runbooks from there. |
| `terminal.timeout` | at least 900 | Some fleet commands, such as a bootstrap, take minutes. |
| `skills.external_dirs` | adds `home/hermes/skills` | Hermes finds the `fleet-ops` and `fleet-provision` skills. |
| `skills.auto_load` | adds `fleet-ops` | The everyday skill is always at hand. |
| `approvals.deny` | adds four patterns | Hermes may never run `fleet exec all ... rm -rf`, nor read the secrets folder or a Hermes `.env`, the director's own included. |

It also copies `home/hermes/SOUL.md` into the director's folder (keeping a backup of a
different one) and writes the two scheduled-check scripts into its `scripts/` folder.

**The director's `.env`** holds its own secrets. Set each one with
`hermes -p director config set NAME value`:

| Variable | Meaning |
| --- | --- |
| Your model provider's key, such as `OPENROUTER_API_KEY` | The key the director's model runs on, if your provider uses one. `hermes -p director model` writes it under the provider's own name. |
| `TELEGRAM_BOT_TOKEN` | Your bot's token from @BotFather. A token works in one profile only. |
| `TELEGRAM_ALLOWED_USERS` | Your numeric Telegram user id: the only person the bot answers. |
| `TELEGRAM_HOME_CHANNEL` | Where scheduled messages go; `/sethome` sets it. |
| `HOSTINGER_TOKEN_ACCOUNT_1` to `_5` | Optional Hostinger API tokens, one per account. See [Hostinger API](../home/hostinger-api.md). |

The full template is
[`home/hermes/env.example`](https://github.com/CoffeeTimeGX/hermes-fleet/blob/main/home/hermes/env.example).

## SSH on your PC

`fleet init` creates the fleet key without a passphrase, because the scheduled checks
use it unattended. It opens only the fleet's VPSs, and once they are locked down, only
over Tailscale.

It writes `~/.ssh/config.d/fleet` with one `Host` block per VPS, and adds
`Include config.d/*` at the top of `~/.ssh/config` (after a backup) if it is not there.
`fleet init` rewrites the `config.d/fleet` file from your inventory each time it runs;
`fleet ssh-config` prints the same blocks. On Linux and macOS, `fleet` keeps each SSH
connection open for two minutes and reuses it, which makes series of commands faster.
