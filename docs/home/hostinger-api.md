# Hostinger API (optional)

The fleet works without this page. It gives Hermes a second way into your Hostinger
accounts, through the Hostinger API instead of SSH, so it can:

- reboot a VPS that SSH cannot reach any more,
- read a VPS's state and resource graphs,
- create a snapshot before a risky change.

Hostinger publishes an official MCP server for this. Each of your five Hostinger accounts
has its own API token, so Hermes gets five small MCP servers, one per account.

## 1. Create a token in each Hostinger account

In each account's hPanel, open the **API** page, go to the **API tokens** tab and create
a token. Give it an expiry date you will remember, and copy it.

A token can do everything in its Hostinger account, so it stays on your PC, in the
director's `.env` file, and nowhere else.

## 2. Install the MCP server

It needs [Node.js](https://nodejs.org/) (the LTS version):

```
npm install -g @hostinger/mcp
```

The package includes `hostinger-vps-mcp`, a server with only the VPS tools, which is
all the fleet needs.

## 3. Give the tokens to the director

```
hermes -p director config set HOSTINGER_TOKEN_ACCOUNT_1 <token of account 1>
hermes -p director config set HOSTINGER_TOKEN_ACCOUNT_2 <token of account 2>
...
hermes -p director config set HOSTINGER_TOKEN_ACCOUNT_5 <token of account 5>
```

Use the same numbering as the `hostinger_account` labels in your
[inventory](../reference/config.md#fleetini), so account 1 is the one that owns vps1,
and so on.

## 4. Add the servers to the director

Open the director's configuration with `hermes -p director config edit` and paste the
`mcp_servers:` block
from [`home/hermes/mcp-hostinger.example.yaml`](https://github.com/CoffeeTimeGX/hermes-fleet/blob/main/home/hermes/mcp-hostinger.example.yaml).
Each server reads its token from the variable you set in step 3.

- On Windows, if Hermes cannot start the server, replace `hostinger-vps-mcp` with the
  full path that `where hostinger-vps-mcp` prints.
- Delete the blocks of accounts you do not want to connect. A server without a token
  falls back to an interactive browser sign-in, which does not work unattended.
- Keep `trust: untrusted` on every server. Hermes then asks you before any call that can
  change something, such as a reboot.

Restart Hermes (`hermes gateway restart`) and try: *"Using the Hostinger tools for
account 3, show me the state of its VPS."*

## What to use it for

- **A VPS does not answer SSH.** See [VPS unreachable](../runbooks/vps-unreachable.md):
  Hermes can check the VPS's state in Hostinger and, after you say yes, reboot it.
- **Before a big change** (an OS upgrade, a new provider), ask for a snapshot first.

Do anything destructive, such as reinstalling the operating system or restoring a
snapshot, yourself in hPanel.
