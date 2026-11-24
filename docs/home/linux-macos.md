# Linux and macOS

This page sets up a Linux or macOS computer as the fleet's home machine. On a Windows PC,
use the [Windows page](windows.md) instead (it does not need WSL).

## 1. Before you start

You need `python3` (3.9 or newer), `ssh`, `ssh-keygen`, `git`, `curl` and `tar`.
`rsync` is recommended: pulls can then resume a broken download.

=== "Ubuntu or Debian"

    ```bash
    sudo apt install python3 openssh-client git curl rsync
    ```

=== "Fedora"

    ```bash
    sudo dnf install python3 openssh-clients git curl rsync
    ```

=== "macOS"

    ```bash
    xcode-select --install    # git and python3; ssh, curl and rsync are built in
    ```

Install the [Tailscale app](https://tailscale.com/download) too, and sign in. The
[Tailscale page](../tailscale.md) explains what to set up there.

## 2. Run the installer

```bash
git clone https://github.com/CoffeeTimeGX/hermes-fleet ~/hermes-fleet
cd ~/hermes-fleet && ./home/install.sh
```

It installs Hermes Agent with its official installer if it is missing, then runs
`fleet init`, which creates:

| What | Where |
| --- | --- |
| The `fleet` command | `~/.local/bin/fleet` (a link to `home/bin/fleet` in the repository) |
| Inventory | `~/.config/fleet/fleet.ini` |
| Secrets (mode 600, only you can read them) | `~/.config/fleet/secrets/` |
| Fleet SSH key | `~/.ssh/fleet_ed25519` and `fleet_ed25519.pub` |
| SSH shortcuts, so `ssh vps1` works | `~/.ssh/config.d/fleet`, included from `~/.ssh/config` |
| The director, Hermes' `director` profile: settings, `SOUL.md`, scheduled-check scripts | `~/.hermes/profiles/director/` (`hermes profile show director` prints it) |

Finished jobs will go to `~/fleet-results/`. Running the installer again is safe: it
never overwrites your inventory, your secrets or your key.

Option: `--no-hermes` skips everything about Hermes.

At the end it prints **your fleet public key** (a line starting with `ssh-ed25519`).
You will paste it into Hostinger. Print it again any time with
`cat ~/.ssh/fleet_ed25519.pub`.

If the installer warns that `~/.local/bin` is not on your PATH, add this line to
`~/.bashrc` or `~/.zshrc` and open a new terminal:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## 3. Check the setup

```bash
fleet doctor
```

Every line should say `ok` or `warn`. Warnings about Tailscale, Claude credentials and
node names that do not resolve yet are expected at this stage.

## 4. Choose the director's model

Hermes directs the fleet from its own profile, `director`, which `fleet init` created. A
profile is a separate Hermes with its own settings, model, memory and Telegram bot, so the
fleet work stays apart from anything else you use Hermes for. Commands for the director
have `-p director` in them.

The director runs on a model you choose from any provider Hermes supports. It does not
use Claude: the Claude sessions run on the VPSs, signed in with their own Claude
accounts, and the director hands them the work through the `fleet` command.

1. Pick a provider and create an account there. Nous Portal is the one Hermes
   recommends; OpenRouter, OpenAI, Google Gemini, DeepSeek, Kimi and GLM work too, and
   the [Hermes providers page](https://hermes-agent.nousresearch.com/docs/integrations/providers) lists every one. Set a monthly spend limit
   with the provider if it offers one.
2. Run the model wizard for the director. It signs you in to the provider or asks for
   its API key, and keeps the key in the director's own `.env` file:

    ```bash
    hermes -p director model
    ```

    Choose a model with at least 64,000 tokens of context that is good at tool calls.

3. Try it: run `hermes -p director` and ask *"run fleet list and tell me what you see"*.

`fleet doctor` shows the director's model. Run `hermes -p director model` again to change
it. `fleet init` also made the shortcut `director`, which does the same as
`hermes -p director`.

## 5. Connect Telegram

The short version (details on the [Telegram page](telegram.md)):

1. In Telegram, open **@BotFather**, send `/newbot`, and copy the token.
2. Send a message to **@userinfobot** to get your numeric user id.
3. Run `hermes -p director gateway setup`, choose Telegram, and paste the token and your
   user id.
4. Keep Hermes' gateway running in the background, start it now, and check it. One
   gateway serves every profile, so these commands have no `-p director`:

    ```bash
    hermes gateway install
    hermes gateway start
    hermes gateway status
    ```

    On Linux, if the computer runs without anyone logged in, also run
    `sudo loginctl enable-linger $USER` so background services keep running after you
    log out.

5. In the chat with your bot, send `/sethome` (scheduled reports go there), then ask it
   *"fleet status"*.

## 6. Turn on the scheduled checks

```bash
fleet hermes-cron
```

Five cron jobs for the director: a health check every 10 minutes that messages you only
when something changes, a pull every 30 minutes, a daily report at 9 am, the week plan's
hourly queueing, and next week's topics on Sundays. See
[Scheduled checks](../operations/scheduled-checks.md).

## 7. Next

- Keep the computer awake when it should be working: [Keep it running](always-on.md).
- Set up [Tailscale](../tailscale.md), then [create the VPSs](../vps/hostinger.md).

!!! note "WSL2"
    `install.sh` also works inside WSL2, but on a Windows PC the native Windows setup is
    simpler: WSL2 stops when idle, and Tailscale then has to run inside it as well.
