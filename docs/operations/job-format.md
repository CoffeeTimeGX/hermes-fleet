# Job format

A job is a small JSON file that tells one Claude session what to make. Hermes writes
them for you, but you can write your own, keep them in version control and send them
with `fleet dispatch`. Only `prompt` is required.

```json
{
  "channel": "Example Channel",
  "title": "Five facts about Saturn's rings",
  "prompt": "Make one vertical short video (1080x1920, 45 to 60 seconds) for the channel described in ./brief.md ...",
  "files": [
    {"path": "brief.md", "content": "# Example Channel\n\nTone: curious and upbeat ...\n"}
  ],
  "timeout_minutes": 180,
  "max_turns": 300,
  "max_retries": 1
}
```

Check a job without sending it: `fleet dispatch my-job.json --dry-run` prints it as it
would be queued, or says exactly which field is wrong.

## Fields

| Field | What it does | When left out |
| --- | --- | --- |
| `prompt` | The instructions for the session. Required, unless `prompt_file` is given. | |
| `prompt_file` | A text or Markdown file whose content becomes the prompt. The path is relative to the job file. `fleet dispatch` reads it on your PC, so the VPS receives an ordinary `prompt`. | |
| `channel` | Which of your channels the job is for, up to 200 characters. It decides which VPS makes the video: the one whose `channels` names it (capitals, spaces and `-` do not matter, so `Space Facts` and `space-facts` are the same channel). It also goes into the job id, the session's instructions and every report. | `general` |
| `title` | A short title for reports, up to 200 characters. | none |
| `id` | The job's id: letters, digits, `.`, `_` and `-`, up to 128 characters, starting with a letter or a digit. It must not exist yet on the VPS. | made up, for example `20261118-142233-space-facts-k3x9p` (UTC time, channel, random letters) |
| `template` | A folder from `vps/templates/` that is copied into the job's workspace before the session starts. See [Templates](#templates). | none |
| `files` | Files to write into the workspace. See [Files](#files). | none |
| `timeout_minutes` | Stop the job after this many minutes, from 1 to 1440 (24 hours). | 180 |
| `max_retries` | How many times the job starts again after its process was lost, for example when the VPS rebooted, from 0 to 5. A job that fails on its own is not started again; use `fleet retry` for that. | 1 |
| `max_turns` | The most agentic turns the session may take, from 1 to 10000. At the limit, the session stops with an error. | no limit |
| `model` | The Claude model: an alias such as `opus`, `sonnet`, `haiku` or `fable`, or a full model id such as `claude-opus-5-5`. | the account's default |
| `effort` | How hard the model thinks: `low`, `medium`, `high`, `xhigh`, `max` or `ultracode`. Which levels exist depends on the model. `ultracode` is `xhigh` plus permission for Claude to split big tasks over several parallel sub-sessions. Higher levels use up usage limits faster. | the model's default |
| `max_budget_usd` | Stop the session once its estimated cost reaches this many US dollars. Claude Code estimates the cost itself, so leave some headroom. With an API key, this caps what one job can spend. | no cap |
| `permission_mode` | `bypassPermissions`, `dontAsk` or `acceptEdits`. See [Permissions](#permissions). | `bypassPermissions` |
| `allowed_tools` | Tools the session may use without asking, as a list (`["Read", "Bash(ffmpeg *)"]`) or as one comma-separated text. See [Permissions](#permissions). | none |
| `provider` | Which tool runs the job. Only VPSs that list this provider in your inventory receive it. | `claude` |

`fleet dispatch` adds `node` (the VPS) and `submitted_at` (UTC), and `fleet retry` adds
`retry_of`. `fleet handover` adds `handed_over_from` (the VPS the job came from) and
`handed_over_at` (UTC). Fields the fleet does not know are kept in the job's `job.json`
and otherwise ignored, so Hermes can store its own notes in a job, such as a planned
upload date.

### Defaults for one VPS

Some defaults can be set per VPS, in the same secrets file as its Claude credential
(`~/.config/fleet/secrets/<vps>/claude.env` on your PC, then `fleet secrets push claude
<vps>`). A job's own fields always win.

| Variable | Default for |
| --- | --- |
| `ANTHROPIC_MODEL` | `model` |
| `CLAUDE_MAX_TURNS` | `max_turns` |
| `CLAUDE_PERMISSION_MODE` | `permission_mode` |

The defaults for `timeout_minutes` and `max_retries` belong to the worker:
`DEFAULT_TIMEOUT_MINUTES` and `DEFAULT_MAX_RETRIES` in `/etc/fleet/worker.local.env` on
the VPS (see [Worker reference](../reference/worker.md#settings)).

### Options of `fleet dispatch`

- `--channel "Space Facts"` and `--provider claude` replace that field in every job you
  send in that command.
- `--prompt "..."` makes a job from one line of text, without a file.
- The job goes to the VPS that makes its channel. `--to` names another VPS instead: see
  [Everyday use](everyday.md#queue-work).

## The prompt

Each session runs alone, with nobody to answer its questions. Good prompts say:

- exactly what to make, with formats, sizes and lengths (*"1080x1920, 45 to 60 seconds,
  H.264 with AAC audio"*),
- the file names of the deliverables, all in `./output/`,
- what to do when something is unclear (*"make a reasonable choice and list it in your
  summary"*),
- what to put in the final summary.

The fleet adds a note to the session's system prompt in every job. It tells the session
that it runs unattended on a fleet VPS, the channel and job id, that every deliverable
goes in `./output/`, and that its final message is saved as `output/SUMMARY.txt`. You do
not need to repeat that.

**Long prompts.** A prompt over 100,000 characters is written to `JOB_PROMPT.md` in the
workspace, and the session is told to read it first. For long briefs, `prompt_file`
keeps the job file short:

```json
{
  "channel": "Example Channel",
  "title": "Weekly episode from a long brief",
  "prompt_file": "long-brief.md",
  "timeout_minutes": 240
}
```

## Files

`files` puts small files into the workspace before the session starts: a brief, a
script, subtitles, a small logo.

```json
"files": [
  {"path": "brief.md", "content": "# Brief\n\nTopic: ...\n"},
  {"path": "assets/logo.png", "content": "iVBORw0KGgoAAAANSUhEUg...", "encoding": "base64"}
]
```

- `path` is relative to the workspace. It may contain folders, but not `..`, a drive
  letter, or a leading `/` or `\`.
- `encoding` is `utf-8` (the default) for text, or `base64` for binary files.
- Files are written after the template, so a job can replace one template file.
- The whole job travels over SSH and waits in the VPS's queue, so keep it small (a few
  MB at most). Large assets that many jobs share, such as fonts, music or intro clips,
  belong in a template.

## Templates

A template is a folder in the repository, `vps/templates/<name>/`, that is copied into
the workspace of every job that names it. It is the place for everything a channel's
sessions should always have:

```
vps/templates/space-facts/
  CLAUDE.md                          the channel's rules: style, voice, formats
  .claude/skills/<skill>/SKILL.md    Claude Code skills the session can use
  assets/                            fonts, logos, music, intro and outro clips
```

Claude Code reads `CLAUDE.md` and the skills in `.claude/skills/` by itself when the
session starts, because the workspace is its working folder.

1. Create the folder under `vps/templates/`. Use lowercase letters, digits and dashes for
   its name.
2. Run `fleet sync`, which copies the repository's `vps/` folder, templates included, to
   every VPS.
3. Name it in the job: `"template": "space-facts"`.

A job that names a template a VPS does not have fails at once with `bad job: template
'space-facts' is not in vps/templates (run fleet sync)`.

No templates ship with the fleet yet: the skills and `CLAUDE.md` files for each of your
channels are a later step. A template is copied once per job. A job that comes back
after a usage limit or a reboot keeps the workspace it already had.

## Permissions

Nobody watches a session to approve each command, so by default the sessions run with
`bypassPermissions`: Claude Code runs every tool and command without asking. What keeps
that safe enough is where it runs: an unprivileged user on a VPS that holds no secret
except its own Claude credential. See [Security](../reference/security.md).

A job can ask for less:

| `permission_mode` | What the session may do |
| --- | --- |
| `bypassPermissions` | Everything (the default). |
| `dontAsk` | Only what `allowed_tools` lists, plus reading files and read-only commands. Everything else is refused, and the session carries on without it. |
| `acceptEdits` | Create and edit files, and run basic file commands (`mkdir`, `cp`, `mv`, `rm`, `touch`, `sed`). Every other command is refused, so `ffmpeg` would not run. Rarely useful for video. |

For an exact list of allowed tools, combine `dontAsk` with `allowed_tools`. Rules use
Claude Code's syntax: a tool name (`Read`, `Write`, `Edit`) or a command pattern
(`Bash(ffmpeg *)`).

```json
{
  "channel": "Space Facts",
  "prompt": "Turn ./input/script.md into narration subtitles and a 1080x1920 video ...",
  "permission_mode": "dontAsk",
  "allowed_tools": ["Read", "Write", "Edit", "Bash(ffmpeg *)", "Bash(ffprobe *)", "Bash(python3 *)"]
}
```

With `bypassPermissions`, `allowed_tools` changes nothing, because everything is allowed
already.

## Job ids

- A made-up id looks like `20261118-142233-space-facts-k3x9p`: the UTC time it was
  queued, the channel in lowercase, and five random characters.
- `--to all` sends one copy per VPS and adds the VPS to each id
  (`...-k3x9p-vps1`, `...-k3x9p-vps2` and so on).
- `fleet retry` adds `-r1`, then `-r2` for a retry of the retry, and so on.
- `fleet handover` keeps the id. When the other VPS already has a job with that id, the
  moved job gets `-h1` at the end (or `-h2`, and so on).
- An id must be new on its VPS. Sending a job with an id that VPS already has fails
  with `job id ... already exists`.

## Examples

The repository has three example jobs in `jobs/examples/`:

| File | What it shows |
| --- | --- |
| `hello-fleet.json` | A two-minute test: a 5-second test video and a text file. Send it with `--to all` to check every VPS. |
| `short-video.json` | A vertical short with a brief sent in `files`. |
| `long-brief.json` | A long-form episode whose prompt comes from `long-brief.md` through `prompt_file`. |
