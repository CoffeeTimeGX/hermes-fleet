#!/usr/bin/env bash
# Install the Claude Code skills that every VPS has, for the `fleet` user.
#
# The list is skills.json next to this script (vps/skills/skills.json in the repository).
# Each skill goes to ~/.claude/skills/<name>/, where every Claude Code session of this
# user finds it, at the exact tag and commit the list names. A skill that needs Node.js
# gets the Node.js version the list names, in ~/.local/share/fleet/node, linked from
# ~/.local/bin (the jobs have that folder first on their PATH).
#
# The home machine runs it for you:  fleet skills install <node|all>
# By hand, as the fleet user:        bash install.sh            install or update
#                                    bash install.sh --check    report only
#                                    bash install.sh --json     report only, as one JSON object
#
# Safe to repeat. A running job keeps working through an update: the previous version of
# a skill moves to ~/.local/share/fleet/skills/old/ instead of being deleted at once.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIST="${FLEET_SKILLS_FILE:-$HERE/skills.json}"
NODE_DIST="${FLEET_NODE_DIST:-https://nodejs.org/dist}"
SKILLS_DIR="$HOME/.claude/skills"
DATA="$HOME/.local/share/fleet"
BIN="$HOME/.local/bin"
MARK=".fleet-skill.json"

mode=install
for a in "$@"; do
  case "$a" in
    --check) mode=check ;;
    --json) mode=json ;;
    *) echo "usage: install.sh [--check|--json]" >&2; exit 64 ;;
  esac
done

fail() { echo "skills: $*" >&2; exit 1; }

if [[ "$(id -u)" -eq 0 && "${FLEET_SKILLS_ALLOW_ROOT:-}" != 1 ]]; then
  fail "run this as the fleet user, not root: the skills are for the fleet user's Claude Code sessions"
fi
for bin in curl git jq sha256sum tar flock; do
  command -v "$bin" >/dev/null 2>&1 || fail "missing $bin: run the VPS bootstrap first"
done
[[ -f "$LIST" ]] || fail "no skills list at $LIST (on the home machine: fleet sync)"
jq -e '.skills | type == "array"' "$LIST" >/dev/null 2>&1 || fail "$LIST is not a skills list"
export PATH="$BIN:$PATH"

# Is version $1 at least $2? Both are dotted numbers such as 22.23.5 and 22.20.
ver_ge() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]; }

node_now() { node --version 2>/dev/null | head -n1 | sed 's/^v//' || true; }

# The highest Node.js version any listed skill needs; empty when none needs Node.js.
node_need() { jq -r '[.skills[].node // empty | tostring] | .[]' "$LIST" | sort -V | tail -n1; }

node_arch() {
  case "$(uname -m)" in
    x86_64 | amd64) echo x64 ;;
    aarch64 | arm64) echo arm64 ;;
    *) fail "no Node.js build for this processor ($(uname -m))" ;;
  esac
}

# The Node.js the list names, for the fleet user only. A node in ~/.local/bin that is not
# a link the fleet made (one you installed yourself) is kept when it is new enough.
ensure_node() {
  local need="$1" want arch sha name dir tmp b prev=""
  want="$(jq -r '.node.version // empty' "$LIST")"
  [[ "$want" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "$LIST: node.version must be a version like 22.23.5"
  ver_ge "$want" "$need" || fail "$LIST: node.version $want is older than the $need a skill needs"
  if [[ -L "$BIN/node" && "$(readlink "$BIN/node")" == "$DATA/node/"* ]]; then
    prev="$(readlink "$BIN/node")"
    prev="${prev%/bin/node}"
  elif [[ -e "$BIN/node" || -L "$BIN/node" ]]; then
    ver_ge "$(node_now)" "$need" || fail "$BIN/node is Node.js $(node_now), not $need or newer; remove it, then run this again"
    echo "node: keeping your own Node.js $(node_now) in $BIN"
    return
  fi
  arch="$(node_arch)"
  name="node-v$want-linux-$arch"
  dir="$DATA/node/$name"
  if [[ "$prev" == "$dir" && -x "$dir/bin/node" ]]; then
    echo "node: Node.js $want, up to date"
    return
  fi
  if [[ ! -x "$dir/bin/node" ]]; then
    sha="$(jq -r --arg a "$arch" '.node.sha256[$a] // empty' "$LIST")"
    [[ "$sha" =~ ^[0-9a-f]{64}$ ]] || fail "$LIST: no sha256 for the $arch build of Node.js $want"
    mkdir -p "$DATA/node"
    tmp="$(mktemp -d "$DATA/node/.download.XXXXXX")"
    echo "node: downloading Node.js $want ($arch)"
    if ! curl -fsSL --retry 3 -o "$tmp/$name.tar.gz" "$NODE_DIST/v$want/$name.tar.gz"; then
      rm -rf "$tmp"
      fail "could not download $NODE_DIST/v$want/$name.tar.gz"
    fi
    if ! echo "$sha  $tmp/$name.tar.gz" | sha256sum -c --status; then
      rm -rf "$tmp"
      fail "the Node.js download does not match the checksum in $LIST; nothing was installed"
    fi
    tar -xzf "$tmp/$name.tar.gz" -C "$tmp"
    [[ -x "$tmp/$name/bin/node" ]] || { rm -rf "$tmp"; fail "the Node.js download has no bin/node"; }
    rm -rf "$dir"
    mv "$tmp/$name" "$dir"
    rm -rf "$tmp"
  fi
  mkdir -p "$BIN"
  for b in node npm npx; do
    if [[ -e "$BIN/$b" || -L "$BIN/$b" ]] && [[ "$(readlink "$BIN/$b" || true)" != "$DATA/node/"* ]]; then
      echo "node: keeping your own $BIN/$b"
    elif [[ -e "$dir/bin/$b" ]]; then
      ln -sfn "$dir/bin/$b" "$BIN/$b"
    fi
  done
  echo "node: installed Node.js $want in $dir"
  # Keep the version a running job may still use, delete the older ones.
  for old in "$DATA"/node/node-v*; do
    [[ -d "$old" && "$old" != "$dir" && "$old" != "$prev" ]] && rm -rf "$old"
  done
  return 0
}

installed_commit() { jq -r '.commit // empty' "$SKILLS_DIR/$1/$MARK" 2>/dev/null || true; }
installed_tag() { jq -r '.tag // empty' "$SKILLS_DIR/$1/$MARK" 2>/dev/null || true; }

# Move a skill's folder out of the way (not deleted yet: a running job may still use it).
retire() {
  local name="$1"
  mkdir -p "$DATA/skills/old"
  rm -rf "$DATA/skills/old/$name"
  mv "$SKILLS_DIR/$name" "$DATA/skills/old/$name"
}

install_skill() {
  local name="$1" repo="$2" tag="$3" commit="$4" stage had head
  if [[ -e "$SKILLS_DIR/$name" && ! -f "$SKILLS_DIR/$name/$MARK" ]]; then
    fail "$SKILLS_DIR/$name was not installed by the fleet; move it away, then run this again"
  fi
  if [[ "$(installed_commit "$name")" == "$commit" ]]; then
    echo "$name: $tag, up to date"
    return
  fi
  had="$(installed_tag "$name")"
  stage="$DATA/skills/new/$name"
  rm -rf "$stage"
  mkdir -p "$DATA/skills/new"
  echo "$name: downloading $tag from $repo"
  if ! GIT_TERMINAL_PROMPT=0 git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$tag" -- "$repo" "$stage"; then
    rm -rf "$stage"
    fail "$name: could not download $tag from $repo"
  fi
  head="$(git -C "$stage" rev-parse HEAD)"
  if [[ "$head" != "$commit" ]]; then
    rm -rf "$stage"
    fail "$name: $tag is now commit ${head:0:12}, not the ${commit:0:12} in the list; nothing changed (check the release, then update skills.json)"
  fi
  rm -rf "$stage/.git"
  jq -n --arg n "$name" --arg r "$repo" --arg t "$tag" --arg c "$commit" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{name: $n, repo: $r, tag: $t, commit: $c, installed_at: $at, by: "hermes-fleet vps/skills/install.sh"}' \
    >"$stage/$MARK"
  mkdir -p "$SKILLS_DIR"
  [[ -e "$SKILLS_DIR/$name" ]] && retire "$name"
  mv "$stage" "$SKILLS_DIR/$name"
  if [[ -n "$had" ]]; then
    echo "$name: updated from $had to $tag"
  else
    echo "$name: installed $tag"
  fi
}

listed() { jq -r '.skills[].name' "$LIST"; }

check_names() {
  local name repo tag commit
  while IFS=$'\t' read -r name repo tag commit; do
    [[ "$name" =~ ^[a-z0-9][a-z0-9-]{0,63}$ ]] || fail "$LIST: skill name '$name' must be lowercase letters, digits and dashes"
    [[ "$repo" =~ ^(https://|file://|/) ]] || fail "$LIST: $name: repo must be an https:// address"
    [[ "$tag" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || fail "$LIST: $name: tag '$tag' is not a tag name"
    [[ "$commit" =~ ^[0-9a-f]{40}$ ]] || fail "$LIST: $name: commit must be the tag's full 40-character commit id"
  done < <(jq -r '.skills[] | [.name, .repo, .tag, .commit] | map(. // "" | tostring) | @tsv' "$LIST")
  [[ -z "$(listed | sort | uniq -d)" ]] || fail "$LIST: a skill is listed twice"
}

report() {
  local need now ok=true node_ok=true rows="[]" name tag commit have state
  need="$(node_need)"
  now="$(node_now)"
  if [[ -n "$need" ]] && ! { [[ -n "$now" ]] && ver_ge "$now" "$need"; }; then
    node_ok=false ok=false
  fi
  while IFS=$'\t' read -r name tag commit; do
    have="$(installed_commit "$name")"
    if [[ -e "$SKILLS_DIR/$name" && ! -f "$SKILLS_DIR/$name/$MARK" ]]; then
      state="not installed by the fleet"
    elif [[ -z "$have" ]]; then
      state="missing"
    elif [[ "$have" != "$commit" ]]; then
      state="outdated ($(installed_tag "$name"))"
    else
      state="ok"
    fi
    [[ "$state" == ok ]] || ok=false
    rows="$(jq -c --arg n "$name" --arg t "$tag" --arg s "$state" '. + [{name: $n, tag: $t, state: $s, ok: ($s == "ok")}]' <<<"$rows")"
    if [[ "$mode" == check ]]; then
      echo "$name $tag: $state"
    fi
  done < <(jq -r '.skills[] | [.name, .tag, .commit] | @tsv' "$LIST")
  if [[ "$mode" == check ]]; then
    if [[ -n "$need" ]]; then
      echo "node: ${now:-not installed} (the skills need $need or newer): $([[ "$node_ok" == true ]] && echo ok || echo PROBLEM)"
    fi
    [[ "$ok" == true ]] || echo "fix: on the home machine, fleet skills install $(hostname -s)"
  else
    jq -nc --argjson s "$rows" --arg v "$now" --arg need "$need" --argjson nok "$node_ok" --argjson ok "$ok" \
      '{skills: $s, node: {version: (if $v == "" then null else $v end), needs: (if $need == "" then null else $need end), ok: $nok}, ok: $ok}'
  fi
  [[ "$ok" == true ]]
}

check_names
if [[ "$mode" != install ]]; then
  report
  exit
fi

mkdir -p "$DATA"
exec 9>"$DATA/skills.lock"
flock -w 900 9 || fail "another skills install is still running on this VPS"

echo "==> Claude Code skills for $(whoami) on $(hostname -s)"
need="$(node_need)"
[[ -n "$need" ]] && ensure_node "$need"
n=0
while IFS=$'\t' read -r name repo tag commit; do
  install_skill "$name" "$repo" "$tag" "$commit"
  n=$((n + 1))
done < <(jq -r '.skills[] | [.name, .repo, .tag, .commit] | @tsv' "$LIST")

# A skill the fleet installed that is no longer on the list leaves too.
if [[ -d "$SKILLS_DIR" ]]; then
  for d in "$SKILLS_DIR"/*/; do
    name="$(basename "$d")"
    [[ -f "$d/$MARK" ]] || continue
    if ! listed | grep -qxF "$name"; then
      retire "$name"
      echo "$name: removed (no longer in the list)"
    fi
  done
fi
echo "==> $n skill(s) ready. Claude Code sessions that start from now on can use them."
