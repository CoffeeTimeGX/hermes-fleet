#!/usr/bin/env bash
# Install or update Claude Code for the `fleet` user on this VPS.
#
# The home machine runs it for you:  fleet provider install claude <node|all> [--version V]
# By hand, as the fleet user (never root):  bash install.sh [stable|latest|<version>]
set -euo pipefail

CHANNEL="${1:-${CLAUDE_CODE_CHANNEL:-stable}}"
ENV_DIR="$HOME/.config/fleet/providers"
ENV_FILE="$ENV_DIR/claude.env"
SETTINGS="$HOME/.claude/settings.json"

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run this as the fleet user, not root: Claude Code refuses unattended mode as root." >&2
  exit 1
fi
if ! [[ "$CHANNEL" =~ ^(stable|latest|[0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
  echo "Version must be stable, latest or a version number like 2.1.300 (got '$CHANNEL')." >&2
  exit 1
fi
for bin in curl jq; do
  command -v "$bin" >/dev/null 2>&1 || { echo "missing $bin: run the VPS bootstrap first" >&2; exit 1; }
done

echo "==> Installing Claude Code ($CHANNEL) for $(whoami) on $(hostname -s)"
# Anthropic's native installer: puts the launcher in ~/.local/bin/claude, no Node.js needed.
# CLAUDE_INSTALLER may name a local copy of the installer (offline installs and tests).
if [[ -n "${CLAUDE_INSTALLER:-}" ]]; then
  bash "$CLAUDE_INSTALLER" "$CHANNEL"
else
  curl -fsSL https://claude.ai/install.sh | bash -s "$CHANNEL"
fi

# SSH sessions and the worker find it through ~/.local/bin.
if ! grep -qs 'HOME/.local/bin' "$HOME/.profile"; then
  # shellcheck disable=SC2016
  printf '\n# added by hermes-fleet\nexport PATH="$HOME/.local/bin:$PATH"\n' >>"$HOME/.profile"
fi
export PATH="$HOME/.local/bin:$PATH"

# The credentials file is filled from the home machine: fleet secrets push claude <node>
umask 077
mkdir -p "$ENV_DIR"
if [[ ! -f "$ENV_FILE" ]]; then
  cat >"$ENV_FILE" <<'ENVEOF'
# Filled from the home machine with: fleet secrets push claude <node>
# ANTHROPIC_API_KEY=
# CLAUDE_CODE_OAUTH_TOKEN=
ENVEOF
fi
chmod 600 "$ENV_FILE"

# Fleet-wide Claude Code settings. Updates happen only when you run
# `fleet provider install claude ...`, so all five VPSs stay on one version.
mkdir -p "$HOME/.claude"
[[ -s "$SETTINGS" ]] || echo '{}' >"$SETTINGS"
tmp="$(mktemp)"
jq --arg ch "$( [[ "$CHANNEL" == latest ]] && echo latest || echo stable )" \
   '.env = ((.env // {}) + {DISABLE_AUTOUPDATER: "1"})
    | .autoUpdatesChannel = $ch
    | .cleanupPeriodDays = (.cleanupPeriodDays // 14)' "$SETTINGS" >"$tmp"
mv -f "$tmp" "$SETTINGS"

version="$(claude --version 2>/dev/null | head -n1 || true)"
if [[ -z "$version" ]]; then
  echo "Claude Code did not install correctly (claude --version failed)." >&2
  exit 1
fi
echo "==> Installed: $version"
echo "==> Next, on the home machine: fleet secrets push claude $(hostname -s), then fleet provider check claude $(hostname -s) --smoke"
