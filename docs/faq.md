# FAQ

## The fleet

**Can the VPSs talk to each other?**
No. Every connection starts at your PC: Hermes reaches each VPS over SSH. The Tailscale
policy stops the VPSs from reaching your PC or each other, so a VPS that went wrong
could not touch the rest. When one job needs what another made, Hermes pulls it to your
PC and sends it with the next job.

**Does my PC have to stay on?**
Only for talking to Hermes, queuing work and the scheduled checks. The VPSs keep working
through their queues while it is off and keep their results until it is back. See
[Keep it running](home/always-on.md).

**Why five Claude sessions, and can a VPS run more?**
One session per VPS is the safe start for video work. A bigger VPS can run more at the
same time: raise `sessions` for it in your inventory and re-run
`fleet bootstrap <vps> --skip-upgrade`. Each VPS still uses one Claude account, so more
sessions on one VPS reach its usage limits sooner.

**Can I add a sixth VPS?**
Yes. Add a section to your inventory and provision it like the others. See
[Add a sixth VPS](reference/config.md#add-a-sixth-vps).

**Which VPS makes a video?**
The one that makes videos for the job's channel: the `channels` line of each VPS in your
inventory. Work never moves to another VPS by itself, not even when that VPS is busy or
at its usage limit. See [Queue work](operations/everyday.md#queue-work).

**Can I move work to another VPS?**
Yes, when you say so. Ask the director (*"Move vps2's waiting jobs to vps4"*) or run
`fleet handover vps2 vps4`. To give a channel to another VPS for good, change `channels`
in your inventory. See [Move work to another VPS](operations/everyday.md#move-work-to-another-vps).

**What happens when a Claude account reaches its usage limit?**
That VPS waits for the reset, then continues the interrupted job where it stopped. New
jobs for its channel wait there too, unless you move them with `fleet handover`. See
[Usage limits](operations/usage-limits.md).

**Where are my videos?**
In `fleet-results/<vps>/<job-id>/output/` in your home folder, once they are pulled.
See [Results](operations/results.md).

**Can I use the fleet without Hermes?**
Yes. Every action is a `fleet` command you can run yourself; Hermes only runs the same
commands for you. See the [command reference](reference/cli.md).

**Can I run Hermes on a VPS instead of my PC?**
It would work, but this fleet keeps the director at home on purpose: your secrets stay
on a machine you control, and the VPSs stay simple and replaceable. See
[How it works](architecture.md#why-one-director-and-no-hermes-on-the-vpss).

## Claude and costs

**Is running several Claude accounts allowed?**
Anthropic's terms set no limit on the number of accounts, and the Claude Code team has
said that several Max accounts are not against them. What is forbidden is sharing
accounts, reselling access, or using accounts to avoid detection. Read
[Claude accounts and Anthropic's rules](providers/claude-accounts.md) before you start.

**Subscription tokens or API keys?**
The fleet signs each VPS in with a subscription token by default: a fixed monthly price,
with 5-hour and weekly limits. An API key costs per use and has no such limits, and is
what Anthropic recommends for business use. Each VPS can use either, and switching takes
a minute. See [Claude accounts](providers/claude-accounts.md#the-two-ways-a-vps-can-sign-in).

**What does the fleet cost to run?**
Five Hostinger VPS plans, the five Claude subscriptions (or the API usage of the VPSs
that use keys), and the use of Hermes' model with the provider you chose. Hermes' usage
is small: the scheduled health checks and pulls do not use its model, only your
conversations and the daily report do.

**Which model does Hermes use?**
One you choose, from any provider Hermes supports, such as Nous Portal, OpenRouter,
OpenAI or Google Gemini. Hermes does not use Claude. The VPSs run Claude Code with your
Claude subscriptions, and Hermes hands them the video work through the `fleet` command.
Choose the model with `hermes -p director model`. See
[Windows step 4](home/windows.md#4-choose-the-directors-model).

## Making videos

**How do the sessions learn my channels' style?**
Through job templates: a folder per channel with a `CLAUDE.md` and Claude Code skills,
copied into every job for that channel. The fleet supports them now; writing them for
your channels is the next step. See [Templates](operations/job-format.md#templates).

**Can the sessions use my Claude Projects?**
Not directly. Claude Projects are used in the Claude apps, and Claude Code on the command
line cannot open them. The command-line version of a project is a template folder: put
the project's instructions in the template's `CLAUDE.md` and its reference files next to
it. See [Templates](operations/job-format.md#templates).

**Can a job use files I give it?**
Small files go inside the job (`files`). Large assets that many jobs share, such as
fonts, music or intros, belong in a template. See [Job format](operations/job-format.md#files).

**What tools do the sessions have?**
Everything the bootstrap installs: ffmpeg, ImageMagick, Python with pip and venv, git,
fonts and build tools. A session can add more for itself as the `fleet` user, such as
Python packages in a virtual environment, but not system packages.

## Other tools

**Can I use another AI tool than Claude Code?**
Yes, later. The fleet calls each tool through a small adapter, so another one can run
next to Claude Code without changes to the rest. See
[Add another provider](providers/adding-a-provider.md).

## Housekeeping

**How do I update everything?**
See [Updates](operations/updates.md).

**How do I remove the fleet?**
On each Hostinger account, cancel or delete the VPS. In the Tailscale admin console,
remove the VPS machines. On your PC, delete the director with
`hermes profile delete director` (its settings, Telegram bot settings and scheduled jobs
go with it). Then delete the repository folder, `~/.config/fleet`, `~/fleet-results`
(once you have kept what you want), the fleet key `~/.ssh/fleet_ed25519*` and
`~/.ssh/config.d/fleet`. To remove Hermes too: `hermes uninstall`.
