# Skills on the VPSs

Every VPS has the same Claude Code skills, so every job can use them. The first one is
[Lumina SFX](https://github.com/LuminaBench/lumina-sfx), for sound effects. The list is
[`vps/skills/skills.json`](https://github.com/CoffeeTimeGX/hermes-fleet/blob/main/vps/skills/skills.json)
in this repository: to add a skill, add it there, and every VPS gets it.

## Install them

On your PC:

```powershell
fleet skills install all
```

It copies the fleet code to the VPSs (as `fleet sync` does), then installs the listed
skills on each VPS for the `fleet` user, in `~/.claude/skills/`. Jobs that start from
then on can use them. A new VPS gets them with Claude Code: `fleet provider install
claude vps1` installs the skills too.

Check them at any time:

```powershell
fleet skills
```

It prints one line per skill and VPS, such as `lumina-sfx v1.5.0: ok`, and says how to
fix a VPS that lacks one. `fleet skills list` shows the list itself, without asking the
VPSs.

## Lumina SFX

An offline sound studio for coding agents: more than 2,800 editable sound effects
(ambience and weather, footsteps and other foley, clicks and other interface sounds,
impacts, animals, vehicles), which a session can search, layer and export as WAV files.
It runs on the VPS itself, with no account, no key and nothing to pay.

- **What a job can ask for:** for example *"Use the lumina-sfx skill for the sound
  effects: a cave ambience loop, a heartbeat, a deep boom, a whoosh. Export WAVs and mix
  them under the voice."* Each session is also told which skills its VPS has.
- **What it needs:** Node.js 22.20 or newer. The install puts Node.js 22 in the `fleet`
  user's folders, only for the jobs, and checks the download against the checksum in
  `skills.json`. The Ogg and Opus exports use the `ffmpeg` the VPS already has.
- **Its licence:** the code is MIT. The sounds are under the *Lumina Open Game Audio
  License 1.0*: you may use them in personal or commercial videos, and monetize those
  videos, with no royalties and no credit needed. You may not share the sounds
  themselves as a sound pack, a sample library or a training dataset. The recordings the
  library is built from are all CC0 (public domain). Read the full
  [licence](https://github.com/LuminaBench/lumina-sfx/blob/main/LICENSE).

## Updates

Each skill is pinned to one release (`tag`) and its exact commit (`commit`), so all five
VPSs run the same version, and a release that changes after the fact is refused. To move
to a newer release, change both in `skills.json`, then:

```powershell
git pull
fleet skills install all
```

A job that is running keeps working: the previous version moves to
`~/.local/share/fleet/skills/old/` on the VPS and stays there until the next update. A
skill taken off the list leaves the VPSs the same way. A skill folder that the fleet did
not install (one you put there yourself) is never replaced or removed.

## Add a skill

Add an entry to `vps/skills/skills.json`:

| Field | What it is |
| --- | --- |
| `name` | The skill's folder name: lowercase letters, digits and dashes. |
| `about` | A few words on what it does. Each session reads them. |
| `repo` | The skill's GitHub repository, with its `SKILL.md` at the top. |
| `tag` | The release to install. |
| `commit` | That release's full commit id (40 characters, on the release's page on GitHub). |
| `node` | Optional: the Node.js version it needs, such as `22.20`. |

Then run `fleet skills install all`. Read a skill's instructions and licence before you
add it: every job on every VPS can run what it contains.

A skill for one channel only belongs in that channel's [job template](../operations/job-format.md#templates)
instead (`vps/templates/<name>/.claude/skills/`).
