#!/usr/bin/env bash
# Local test of vps/skills/install.sh, with no network: a git repository and a Node.js
# download made on the spot stand in for GitHub and nodejs.org.
#   bash tests/skills-local.sh
# `a && pass ... || fail ...` is the intended style: pass never fails.
# shellcheck disable=SC2015
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
pass() { echo "ok   $*"; }
fail() { echo "FAIL $*" >&2; exit 1; }

export HOME="$T/home" FLEET_SKILLS_ALLOW_ROOT=1 FLEET_NODE_DIST="file://$T/dist" FLEET_SKILLS_FILE="$T/skills.json"
mkdir -p "$HOME"
SKILLS="$HOME/.claude/skills"
DATA="$HOME/.local/share/fleet"
run() { bash "$ROOT/vps/skills/install.sh" "$@" >"$T/out.txt" 2>&1; }
says() { grep -qF -- "$1" "$T/out.txt" || { cat "$T/out.txt" >&2; fail "expected: $1"; }; }

case "$(uname -m)" in
  aarch64 | arm64) arch=arm64 ;;
  *) arch=x64 ;;
esac

# Fake Node.js releases: 99.1.0, and 99.2.0 for the checksum test.
fake_node() {
  local ver="$1" name="node-v$1-linux-$arch"
  mkdir -p "$T/build/$name/bin" "$T/dist/v$ver"
  printf '#!/bin/sh\necho v%s\n' "$ver" >"$T/build/$name/bin/node"
  printf '#!/bin/sh\necho 10.0.0\n' >"$T/build/$name/bin/npm"
  cp "$T/build/$name/bin/npm" "$T/build/$name/bin/npx"
  chmod +x "$T/build/$name/bin/"*
  tar -czf "$T/dist/v$ver/$name.tar.gz" -C "$T/build" "$name"
  sha256sum "$T/dist/v$ver/$name.tar.gz" | cut -d' ' -f1
}
sha1="$(fake_node 99.1.0)"
fake_node 99.2.0 >/dev/null

# A fake skill repository with two releases.
G=(git -C "$T/repo" -c user.name=test -c user.email=test@example.invalid -c commit.gpgsign=false)
git init -q "$T/repo"
printf -- '---\nname: demo-sfx\ndescription: demo\n---\nversion one\n' >"$T/repo/SKILL.md"
"${G[@]}" add SKILL.md && "${G[@]}" commit -qm one && "${G[@]}" tag v1.0.0
c1="$("${G[@]}" rev-parse HEAD)"
printf -- '---\nname: demo-sfx\ndescription: demo\n---\nversion two\n' >"$T/repo/SKILL.md"
"${G[@]}" commit -qam two && "${G[@]}" tag v2.0.0
c2="$("${G[@]}" rev-parse HEAD)"

# skills.json: list TAG COMMIT [NODE_VERSION [NODE_SHA]]; with no TAG, an empty list.
list() {
  jq -n --arg t "${1:-}" --arg c "${2:-}" --arg nv "${3:-99.1.0}" --arg ns "${4:-$sha1}" --arg arch "$arch" \
        --arg repo "file://$T/repo" \
    '{node: {version: $nv, sha256: {($arch): $ns}},
      skills: (if $t == "" then [] else [{name: "demo-sfx", repo: $repo, tag: $t, commit: $c, node: "22.20"}] end)}' \
    >"$FLEET_SKILLS_FILE"
}

echo "== skills install"
list v1.0.0 "$c1"
run --check && fail "--check passed before anything was installed"
says "demo-sfx v1.0.0: missing"
says "fleet skills install"
pass "--check reports a missing skill and how to fix it"

run || { cat "$T/out.txt"; fail "install"; }
says "node: installed Node.js 99.1.0"
says "demo-sfx: installed v1.0.0"
grep -q "version one" "$SKILLS/demo-sfx/SKILL.md" && pass "the skill is in ~/.claude/skills at its tag" || fail "SKILL.md"
[[ ! -e "$SKILLS/demo-sfx/.git" ]] && pass "without its git history" || fail ".git left behind"
[[ "$(jq -r .commit "$SKILLS/demo-sfx/.fleet-skill.json")" == "$c1" ]] && pass "the marker names its commit" || fail "marker"
[[ "$("$HOME/.local/bin/node" --version)" == v99.1.0 ]] && pass "Node.js is linked from ~/.local/bin" || fail "node link"
[[ -L "$HOME/.local/bin/npx" ]] && pass "npm and npx too" || fail "npx link"

run || { cat "$T/out.txt"; fail "second install"; }
says "node: Node.js 99.1.0, up to date"
says "demo-sfx: v1.0.0, up to date"
pass "a second run changes nothing"

run --check || { cat "$T/out.txt"; fail "--check after install"; }
says "demo-sfx v1.0.0: ok"
says "node: 99.1.0 (the skills need 22.20 or newer): ok"
run --json || fail "--json after install"
jq -e '.ok and .skills[0].ok and .node.version == "99.1.0"' "$T/out.txt" >/dev/null && pass "--check and --json say ok" || fail "json: $(cat "$T/out.txt")"

echo "== updates"
list v2.0.0 "$c2"
run --check && fail "--check passed with an old version"
says "demo-sfx v2.0.0: outdated (v1.0.0)"
run || { cat "$T/out.txt"; fail "update"; }
says "demo-sfx: updated from v1.0.0 to v2.0.0"
grep -q "version two" "$SKILLS/demo-sfx/SKILL.md" && pass "an update brings the new tag" || fail "update content"
grep -q "version one" "$DATA/skills/old/demo-sfx/SKILL.md" && pass "the previous version waits in old/ for running jobs" || fail "old copy"

list v2.0.0 "$c1"
run && fail "a moved tag was installed"
says "v2.0.0 is now commit ${c2:0:12}, not the ${c1:0:12}"
grep -q "version two" "$SKILLS/demo-sfx/SKILL.md" && pass "a tag that moved is refused, the skill stays as it was" || fail "moved tag"

list v2.0.0 "$c2" 99.2.0 "$(printf '0%.0s' {1..64})"
run && fail "a bad Node.js download was installed"
says "does not match the checksum"
[[ "$("$HOME/.local/bin/node" --version)" == v99.1.0 ]] && pass "a Node.js download with the wrong checksum is refused" || fail "checksum"
[[ ! -e "$DATA/node/node-v99.2.0-linux-$arch" ]] || fail "the bad download was kept"

echo "== what the fleet did not install"
mkdir -p "$SKILLS/mine"
echo "my own" >"$SKILLS/mine/SKILL.md"
list v2.0.0 "$c2"
jq '.skills += [{name: "mine", repo: .skills[0].repo, tag: "v1.0.0", commit: .skills[0].commit}]' "$FLEET_SKILLS_FILE" >"$T/l.json"
mv "$T/l.json" "$FLEET_SKILLS_FILE"
run && fail "a skill the fleet did not install was replaced"
says "$SKILLS/mine was not installed by the fleet"
grep -q "my own" "$SKILLS/mine/SKILL.md" && pass "your own skill of the same name is left alone" || fail "own skill"

list
run || { cat "$T/out.txt"; fail "empty list"; }
says "demo-sfx: removed (no longer in the list)"
[[ ! -e "$SKILLS/demo-sfx" && -d "$DATA/skills/old/demo-sfx" && -d "$SKILLS/mine" ]] \
  && pass "a skill taken off the list leaves; your own stays" || fail "removal"

rm -f "$HOME/.local/bin/node"
printf '#!/bin/sh\necho v22.0.0\n' >"$HOME/.local/bin/node"
chmod +x "$HOME/.local/bin/node"
list v2.0.0 "$c2"
run && fail "an old Node.js of your own was accepted"
says "is Node.js 22.0.0, not 22.20 or newer"
pass "your own Node.js is kept, and refused when it is too old"

if [[ "$(id -u)" -eq 0 ]]; then
  FLEET_SKILLS_ALLOW_ROOT='' run && fail "ran as root"
  says "not root"
  pass "refuses to run as root"
fi
echo "skills-local: all passed"
