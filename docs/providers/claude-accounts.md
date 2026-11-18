# Claude accounts and Anthropic's rules

Each VPS signs in to Claude on its own. This page explains the two ways to do that, what
Anthropic's published rules say about running Claude Code on servers, and how the fleet
keeps you on the right side of them.

!!! note "Not legal advice"
    This is a plain-language summary of Anthropic's published terms and public statements
    as of November 2026, with links to the sources at the end. Rules change: read the
    sources, and when in doubt, ask Anthropic.

## The two ways a VPS can sign in

| | Subscription token (the fleet's default) | Console API key |
| --- | --- | --- |
| What it is | A one-year token from `claude setup-token`, tied to a Claude Pro or Max subscription | A key from [platform.claude.com](https://platform.claude.com) |
| How you pay | A fixed monthly price per account | Per token used |
| Limits | A 5-hour session limit and weekly limits | Rate limits only; no 5-hour or weekly caps |
| Anthropic's guidance | Meant for "ordinary, individual usage" of Claude Code | The method Anthropic recommends for products and business use |
| In the secrets file | `CLAUDE_CODE_OAUTH_TOKEN=` | `ANTHROPIC_API_KEY=` |

A VPS can switch from one to the other in about a minute (see
[Switch a VPS to an API key](#switch-a-vps-to-an-api-key)).

The Hermes director on your PC always uses an API key: Anthropic does not allow
third-party agents such as Hermes to sign in with a subscription.

## What the rules say

**Several accounts are allowed.** Anthropic's Consumer Terms set no limit on how many
accounts one person may have. In February 2026, a member of the Claude Code team said
publicly that having several Max accounts is not against the terms.

**Some things are clearly forbidden.** Anthropic's Usage Policy and terms forbid sharing
an account with other people, reselling access, creating accounts "to avoid detection",
and opening new accounts to get around a ban.

**Subscriptions are for Claude Code itself.** Claude Code's legal page says subscription
sign-ins are "designed to support ordinary use of Claude Code and other native Anthropic
applications", and that developers building products should use API keys. The fleet's
VPSs run the unmodified Claude Code program, signed in with your own subscription, which
is the use that page allows. Only Hermes, a third-party agent, needs an API key.

**Business use is a grey area.** The same page says the advertised limits of Pro and Max
"assume ordinary, individual usage of Claude Code and the Agent SDK". In February 2026
the Claude Code team said that `claude -p` on a subscription is fine for your own
development work, and that a business built on it should use an API key. Five servers
making videos for your channels sits between the two. It is not a clear breach, but it
is not the case the subscriptions were designed for either.

**Payment.** There is no published rule about payment methods. Paying for all five
accounts with your own card is fine, and it is the honest choice: it shows openly that
the accounts are yours.

## Why accounts get banned

Running Claude around the clock is not itself what gets accounts banned. When people
started running Claude Code nonstop, Anthropic answered with weekly usage limits (since
August 2025): heavy use gets throttled.

The risk is what an unattended fleet can look like:

1. **Automatic abuse filters.** Anthropic has said that some accounts were "automatically
   banned for triggering abuse filters", and that it reversed the bans that were wrong.
   Those filters look for shared and resold accounts. Several paid accounts running at
   their limits all day can resemble a reseller even when they are not one. For you, a
   false positive like that is the main risk.
2. **Business use on consumer plans**, as described above.
3. **Third-party tools signing in with subscriptions.** Anthropic blocked these in
   January 2026, and some of their users were banned. The fleet does not do this: the
   VPSs run Claude Code itself.

Anthropic's legal page also says it may enforce these rules "without prior notice".

## How the fleet keeps the risk low

- **One account per VPS**, and one VPS per account. Tokens are never shared between
  servers or people.
- **Claude Code only.** Each token is made with `claude setup-token`, Anthropic's own
  method for unattended use, and only Claude Code uses it.
- **It stops at the limits.** When an account reaches its 5-hour or weekly limit, its
  VPS stops starting work until the reset instead of retrying against the limit. See
  [Usage limits](../operations/usage-limits.md).
- **Nothing hides the link between the accounts.** Use a separate email address for each
  account, pay for them yourself, and use them only through your own VPSs. Do not use
  separate cards, VPNs or invented identities to make the accounts look unrelated:
  Anthropic's Usage Policy forbids multiple accounts used "to avoid detection", and that
  would turn a grey area into a real violation, putting all five accounts at risk.

Max plans have much higher limits than Pro, which suits video work.

## Get a token for each VPS

Do this on your PC, once per VPS.

1. Create the Claude account for this VPS with its own email address, and subscribe it
   to Pro or Max.
2. Install Claude Code on your PC, if it is not there yet:

    === "Windows (PowerShell)"

        ```powershell
        irm https://claude.ai/install.ps1 | iex
        ```

    === "Linux or macOS"

        ```bash
        curl -fsSL https://claude.ai/install.sh | bash
        ```

3. Sign out of claude.ai in your browser (or use a private window), so the next sign-in
   uses the right account. Then run:

    ```
    claude setup-token
    ```

    Sign in with **this VPS's** Claude account. Claude Code prints a token that starts
    with `sk-ant-oat01-`.

4. Paste it into the VPS's secrets file on your PC, for example
   `~/.config/fleet/secrets/vps1/claude.env`, and leave `ANTHROPIC_API_KEY` empty:

    ```
    CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
    ANTHROPIC_API_KEY=
    ```

5. Push it and test it:

    ```
    fleet secrets push claude vps1
    fleet provider check claude vps1 --smoke
    ```

The token is valid for one year. `fleet health` reminds you a month before it expires;
then repeat these steps (see [Rotate credentials](../runbooks/rotate-credentials.md)).

## If an account is banned

1. That VPS's jobs start failing, and `fleet health` reports `claude not ok`. The other
   VPSs keep working, and `fleet dispatch` stops sending work to the broken one.
2. Appeal through Anthropic support from the account's email address. Do not open a new
   account to replace it while the ban stands.
3. Meanwhile, switch that VPS to an API key (below), or pause it with `fleet pause vps3`.

## Switch a VPS to an API key

1. At [platform.claude.com](https://platform.claude.com), create an API key for the VPS
   (name it after the VPS, for example `vps3`) and set a spend limit.
2. In `~/.config/fleet/secrets/vps3/claude.env` on your PC, fill in
   `ANTHROPIC_API_KEY=sk-ant-api03-...`. When both values are set, Claude Code uses the
   API key, so you can leave the token in place and switch back later by emptying the key.
3. Push and test:

    ```
    fleet secrets push claude vps3
    fleet provider check claude vps3 --smoke
    ```

With an API key, every job costs money in proportion to its work. Give jobs a
`max_budget_usd` (see [Job format](../operations/job-format.md)) so one job cannot run
away with your budget.

## Sources

- [Claude Code: Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)
- [Anthropic Consumer Terms of Service](https://www.anthropic.com/legal/consumer-terms)
- [Anthropic Usage Policy](https://www.anthropic.com/legal/aup)
- [TechCrunch: Anthropic unveils new rate limits to curb Claude Code power users (July 2025)](https://techcrunch.com/2025/07/28/anthropic-unveils-new-rate-limits-to-curb-claude-code-power-users/)
- [Engadget: Anthropic is rate limiting Claude Code (July 2025)](https://www.engadget.com/ai/anthropic-is-rate-limiting-claude-code-blaming-some-users-for-never-turning-it-off-211134730.html)
- [PiunikaWeb: Anthropic's clarification on Max accounts and the Agent SDK (February 2026)](https://piunikaweb.com/2026/02/19/anthropic-claude-max-ban-agent-sdk-clarification/)
- [The Register: Anthropic clarifies ban on third-party Claude access (February 2026)](https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access)
- [MetricNexus: reported causes of Claude account bans (February 2026)](https://metricnexus.ai/blog/anthropic-banning-multiple-claude-accounts)
