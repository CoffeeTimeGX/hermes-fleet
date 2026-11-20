# Rotate credentials

Every secret of the fleet lives on your PC and is changed there. This page covers each
one: when to change it, and how. Hermes can run the commands for you, but you type the
secrets into the files yourself. Never paste a key or token into a chat, Telegram
included.

| Secret | Where it lives | When to change it |
| --- | --- | --- |
| Claude subscription token of a VPS | `~/.config/fleet/secrets/<vps>/claude.env` | Once a year (`fleet health` warns a month before), or if it leaked |
| Claude API key of a VPS | the same file | If it leaked, or when you stop using it |
| The director's model provider key | The director's `.env` | If it leaked |
| Tailscale auth key | `~/.config/fleet/secrets/tailscale.env` | When it expires and you need to set up a VPS |
| Telegram bot token | The director's `.env` | If it leaked |
| Hostinger API tokens | The director's `.env` | When they expire, or if one leaked |
| The fleet SSH key | `~/.ssh/fleet_ed25519` | If your PC was lost, or the key leaked |

## A VPS's Claude subscription token

`claude setup-token` tokens are valid for one year. `fleet health` warns 330 days after
you pushed one.

1. On your PC, sign out of claude.ai in your browser (or use a private window), so the
   next sign-in uses the right account. Run:

    ```
    claude setup-token
    ```

    Sign in with **this VPS's** Claude account and copy the new token
    (`sk-ant-oat01-...`).

2. Open `~/.config/fleet/secrets/vps3/claude.env` and replace the value of
   `CLAUDE_CODE_OAUTH_TOKEN`. Keep `ANTHROPIC_API_KEY` empty.
3. Push it and test it:

    ```
    fleet secrets push claude vps3
    fleet provider check claude vps3 --smoke
    ```

    The push prints `vps3: pushed CLAUDE_CODE_OAUTH_TOKEN` and the check must end with
    `smoke: ok`. The health warning about the token's age goes away.

4. Revoke the old token. Sign in to claude.ai with that account and open
   **Settings > Claude Code**: the **Authorization tokens** list shows every token with
   the date it was made. The list does not say which is which, so revoke the one made
   on the date of the old token. If you cannot tell, leave it: it expires by itself a
   year after it was made. For a token that leaked, also contact Anthropic support.

Jobs that start after the push use the new token. A job that was already running keeps
the old one until it ends; if you revoked that one first, the job fails and you can
`fleet retry` it.

## A VPS's Claude API key

1. At [platform.claude.com](https://platform.claude.com), create a new API key, named
   after the VPS.
2. Put it in `~/.config/fleet/secrets/vps3/claude.env` as `ANTHROPIC_API_KEY`.
3. `fleet secrets push claude vps3`, then `fleet provider check claude vps3 --smoke`.
4. Delete the old key in the Console.

## The director's model provider key

1. Create a new key with the provider the director runs on.
2. Give it to the director with the model wizard, then restart the gateway:

    ```
    hermes -p director model
    hermes gateway restart
    ```

3. Ask the director something, then delete the old key at the provider.

## The Tailscale auth key

The VPSs only use it to join your tailnet during the bootstrap. Once joined, they stay
in it, so an expired auth key affects nothing until you set up or rejoin a VPS.

1. In the Tailscale admin console, create a new key with the same settings as before
   (see [Tailscale, step 4](../tailscale.md#4-create-an-auth-key-for-the-vpss)).
2. Replace `TS_AUTHKEY` in `~/.config/fleet/secrets/tailscale.env`.
3. Revoke the old key under **Settings > Keys** if it has not expired yet.

## The Telegram bot token

1. In Telegram, send `/revoke` to **@BotFather** and choose your bot. It gives you a new
   token and the old one stops working.
2. Run `hermes -p director gateway setup` and enter the new token, then
   `hermes gateway restart`.

## The Hostinger API tokens

1. In the hPanel of the Hostinger account, open the **API** page, **API tokens** tab, and
   create a new token.
2. Give it to the director, for example for the third account, and restart the gateway:

    ```
    hermes -p director config set HOSTINGER_TOKEN_ACCOUNT_3 <new token>
    hermes gateway restart
    ```

3. Delete the old token on the same page.

## The fleet SSH key

Change it if the key may have been copied. Do it in this order, so that you never lose
access: the new key is added everywhere before the old one is removed.

1. Make a new key next to the old one. Press Enter twice when it asks for a passphrase:
   the scheduled checks need a key without one.

    === "Windows (PowerShell)"

        ```powershell
        ssh-keygen -t ed25519 -C hermes-fleet-new -f $HOME\.ssh\fleet_ed25519_new
        ```

    === "Linux or macOS"

        ```bash
        ssh-keygen -t ed25519 -C hermes-fleet-new -f ~/.ssh/fleet_ed25519_new
        ```

2. Print it with `cat ~/.ssh/fleet_ed25519_new.pub` and add it to every VPS, for both
   users, by pasting the whole line into these two commands:

    ```
    fleet exec all -- "echo 'ssh-ed25519 AAAA...new key... hermes-fleet-new' >> ~/.ssh/authorized_keys"
    fleet exec all --root -- "echo 'ssh-ed25519 AAAA...new key... hermes-fleet-new' >> ~/.ssh/authorized_keys"
    ```

    Also add it in hPanel (*VPS > Manage > Settings > SSH keys*) on each Hostinger
    account, so it is used if you ever rebuild a VPS, and remove the old one there.

3. Swap the files, so `fleet` uses the new key:

    === "Windows (PowerShell)"

        ```powershell
        Rename-Item $HOME\.ssh\fleet_ed25519 fleet_ed25519_old
        Rename-Item $HOME\.ssh\fleet_ed25519.pub fleet_ed25519_old.pub
        Rename-Item $HOME\.ssh\fleet_ed25519_new fleet_ed25519
        Rename-Item $HOME\.ssh\fleet_ed25519_new.pub fleet_ed25519.pub
        ```

    === "Linux or macOS"

        ```bash
        mv ~/.ssh/fleet_ed25519 ~/.ssh/fleet_ed25519_old
        mv ~/.ssh/fleet_ed25519.pub ~/.ssh/fleet_ed25519_old.pub
        mv ~/.ssh/fleet_ed25519_new ~/.ssh/fleet_ed25519
        mv ~/.ssh/fleet_ed25519_new.pub ~/.ssh/fleet_ed25519.pub
        ```

        Then wait two minutes: `fleet` keeps SSH connections open that long, and the
        check below must use a new one.

4. Check that the new key works for both users:

    ```
    fleet ping all
    fleet exec all --root -- echo ok
    ```

5. Remove the old key from the VPSs. Copy a part of the old key from the middle of the
   `AAAA...` text in `~/.ssh/fleet_ed25519_old.pub` (about 20 characters), and run,
   for the fleet user first:

    ```
    fleet exec all -- "grep -vF 'PART-OF-OLD-KEY' ~/.ssh/authorized_keys > ~/.ssh/ak && mv ~/.ssh/ak ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
    fleet ping all
    ```

    Then the same for root, with `--root` after `all`, and check with
    `fleet exec all --root -- echo ok`. If a check fails, add the key again through the
    Web Console as in [Provision a VPS, step 1](../vps/provisioning.md#1-get-the-fleet-key-onto-the-vps).

6. Delete `fleet_ed25519_old` and `fleet_ed25519_old.pub` from your PC.

## If your PC is lost or stolen

1. **Remove it from your tailnet at once.** In the Tailscale admin console, open
   **Machines**, find the PC and remove it. Locked-down VPSs accept SSH only over
   Tailscale, so this alone shuts the lost PC out of the fleet.
2. On your new PC, install the fleet ([Windows](../home/windows.md) or
   [Linux and macOS](../home/linux-macos.md)). `fleet init` makes a new fleet key.
3. Add the new public key to each VPS through hPanel's Web Console, for both users
   ([Provision a VPS, step 1](../vps/provisioning.md#1-get-the-fleet-key-onto-the-vps)),
   and delete the old key's line from both `authorized_keys` files.
4. Change every secret that was on the lost PC: each VPS's Claude token or key, Hermes'
   API key, the Telegram bot token, the Hostinger API tokens and the Tailscale auth key,
   as described above.
