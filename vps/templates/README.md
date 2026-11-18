# Job templates

A template is a folder that is copied into a job's workspace before the session
starts. Use it for anything a channel's sessions should always have: a `CLAUDE.md`
with the channel's style rules, Claude Code skills in `.claude/skills/`, brand
assets, fonts or helper scripts.

```
vps/templates/<template-name>/      lowercase letters, digits and dashes
  CLAUDE.md                         read by Claude Code at the start of the session
  .claude/skills/<skill>/SKILL.md   skills the session can use
  assets/...                        anything else the job needs
```

A job picks a template with `"template": "<template-name>"`. After you add or change a
template, run `fleet sync` so every VPS gets it. Files sent inside the job itself
(`"files": [...]`) are written after the template, so they can override a template file
for one job.

No templates ship yet: the channel set-up (skills and CLAUDE.md files) comes later.
