# Windows

This page sets up your Windows PC as the fleet's home machine: Hermes Agent, the `fleet`
command, your inventory and the fleet SSH key. It takes about 20 minutes.

## 1. Before you start

- Windows 10 or 11, signed in with your normal account. Do **not** use an administrator
  PowerShell: everything installs for your user.
- **winget** (the "App Installer"), which Windows 11 and current Windows 10 already have.
  The installer uses it for anything missing: Git for Windows, Python and Tailscale.
- The **OpenSSH Client**, also built in. If the installer says it is missing, add it in
  *Settings > System > Optional features > Add a feature > OpenSSH Client*.

## 2. Run the installer

Open **Windows PowerShell** from the Start menu and paste:

```powershell
irm https://raw.githubusercontent.com/CoffeeTimeGX/hermes-fleet/main/home/install.ps1 | iex
```

It does this, and is safe to run again at any time:

1. Installs Git for Windows, Python 3 and Tailscale if they are missing.
2. Clones this repository to `%USERPROFILE%\hermes-fleet` (or updates it).
3. Installs Hermes Agent with its official installer, if it is not there yet. That
   installer may ask a few questions; the defaults are fine.
4. Adds `%USERPROFILE%\.local\bin` to your PATH and puts the `fleet` command there.
5. Runs `fleet init`, which creates your inventory, the secrets templates, the fleet SSH
   key and the Hermes settings (details below). It never overwrites a file you already
   have.

At the end it prints **your fleet public key**, a line that starts with `ssh-ed25519`.
You will paste it into Hostinger when you create the VPSs. You can print it again any
time with `type $HOME\.ssh\fleet_ed25519.pub`.

??? note "Installer options"
    Run the installer from your copy of the repository to pass options:

    ```powershell
    cd $HOME\hermes-fleet
    powershell -ExecutionPolicy Bypass -File .\home\install.ps1 -KeepModel
    ```

    - `-KeepModel` leaves Hermes' model setting as it is.
    - `-SkipHermes` does not install Hermes (`fleet init` still configures it if present).
    - `-SkipTailscale` does not install Tailscale.
    - `-RepoDir D:\path` keeps the repository somewhere else.

??? info "Where everything is"
    | What | Where |
    | --- | --- |
    | This repository | `%USERPROFILE%\hermes-fleet` |
    | The `fleet` command | `%USERPROFILE%\.local\bin\fleet.cmd` (and `fleet` for Git Bash) |
    | Inventory | `%USERPROFILE%\.config\fleet\fleet.ini` |
    | Secrets (only your user can read them) | `%USERPROFILE%\.config\fleet\secrets\` |
    | Fleet SSH key | `%USERPROFILE%\.ssh\fleet_ed25519` and `fleet_ed25519.pub` |
    | Finished jobs | `%USERPROFILE%\fleet-results\` |
    | Hermes' data (`config.yaml`, `.env`, `SOUL.md`, `scripts\`) | `%LOCALAPPDATA%\hermes\` |

    Elsewhere in these docs, `~` means your home folder, `%USERPROFILE%` on Windows.

## 3. Check the setup

Open a **new** PowerShell window (so it sees the new PATH) and run:

```powershell
fleet doctor
```

Every line should say `ok` or `warn`. At this stage, warnings about Tailscale, Claude
credentials and node names that do not resolve yet are expected: those come later.
A `FAIL` line says what to install or run.

## 4. Give Hermes its API key

Hermes itself runs on Claude through the Claude API. Anthropic requires third-party
agents such as Hermes to use an API key, not a Claude subscription login.

1. Sign in at [platform.claude.com](https://platform.claude.com), add a payment method,
   and create an API key (name it `hermes-director`). Set a monthly spend limit for
   your organization in the Console's limits settings, so a runaway conversation cannot
   surprise you.
2. Give it to Hermes:

    ```powershell
    hermes config set ANTHROPIC_API_KEY sk-ant-api03-...
    ```

    Hermes stores it in `%LOCALAPPDATA%\hermes\.env`. Never paste it into a chat.

3. Try it: run `hermes` and ask *"run fleet list and tell me what you see"*. Hermes runs
   the command in its terminal and describes your five VPSs.

`fleet init` sets Hermes' model to `claude-opus-5-5`, Anthropic's most capable model,
because the director makes the decisions while the VPS sessions do the heavy work. To
use another model: `hermes config set model.default <model id>`.

## 5. Connect Telegram

With Telegram, you can talk to Hermes from your phone and receive its reports. The short
version (details on the [Telegram page](telegram.md)):

1. In Telegram, open **@BotFather**, send `/newbot`, pick a name and a username ending in
   `bot`, and copy the token it gives you.
2. Send any message to **@userinfobot** to get your numeric user id.
3. Run the setup wizard, choose Telegram, and paste the token and your user id:

    ```powershell
    hermes gateway setup
    ```

4. Keep the gateway running whenever you are logged in to Windows, and start it now:

    ```powershell
    hermes gateway install
    hermes gateway start
    hermes gateway status
    ```

    `hermes gateway install` registers a scheduled task named `Hermes_Gateway` that starts
    at logon (Windows asks for permission once).

5. Open your bot in Telegram, send `/sethome` so scheduled reports arrive in this chat,
   then ask it *"fleet status"*.

## 6. Turn on the scheduled checks

```powershell
fleet hermes-cron
```

This creates three Hermes cron jobs: a health check every 10 minutes that messages you
only when something changes, a pull of finished jobs every 30 minutes, and a short
daily report at 9 am. See [Scheduled checks](../operations/scheduled-checks.md).

## 7. Next

- Stop the PC from sleeping when it should be working: [Keep it running](always-on.md).
- Set up [Tailscale](../tailscale.md), then [create the VPSs](../vps/hostinger.md).

## Windows notes

- **Git Bash.** Hermes runs its terminal commands with Git Bash, which is why the
  installer makes sure Git for Windows is present. The `fleet` command works in Git Bash,
  PowerShell and cmd.
- **New PATH.** After the first install, restart the Hermes gateway
  (`hermes gateway restart`) so it sees the `fleet` command.
- **Downloads.** Windows has no rsync, so `fleet pull` downloads each job as a
  compressed archive over SSH. It works the same way, it just cannot resume a broken
  download halfway.
- **What init changed in Hermes.** It copied `SOUL.md` into Hermes' folder (keeping a
  backup of yours), added the repository's skills folder, set the terminal's working
  folder to the repository, raised the terminal timeout to 15 minutes, and added a few
  commands to Hermes' deny list (anything that reads the secrets folder or Hermes' `.env`,
  and `fleet exec all ... rm -rf`). It backs up `config.yaml` before every change.
