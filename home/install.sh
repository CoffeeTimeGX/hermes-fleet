#!/usr/bin/env bash
# Set up the Hermes fleet director on Linux, macOS or WSL2.
#
#   git clone https://github.com/CoffeeTimeGX/hermes-fleet ~/hermes-fleet
#   cd ~/hermes-fleet && ./home/install.sh [--no-hermes] [--keep-model]
#
# Installs Hermes Agent if it is missing, puts `fleet` on your PATH and runs
# `fleet init`. Safe to re-run: your inventory, secrets and SSH key are kept.
# On Windows, use home/install.ps1 instead.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INIT_ARGS=()
INSTALL_HERMES=1
for a in "$@"; do
  case "$a" in
    --no-hermes) INSTALL_HERMES=0; INIT_ARGS+=(--no-hermes) ;;
    --keep-model) INIT_ARGS+=(--keep-model) ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 1 ;;
  esac
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$*"; }

step "Checking prerequisites"
case "$(uname -s)" in
  Linux|Darwin) echo "OS: $(uname -s)" ;;
  *) echo "Use Linux, macOS or WSL2 here. On Windows, run home/install.ps1." >&2; exit 1 ;;
esac
missing=()
for b in python3 ssh ssh-keygen git curl tar; do
  command -v "$b" >/dev/null 2>&1 || missing+=("$b")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Missing: ${missing[*]}. Install them with your package manager, then run this again." >&2
  exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || { echo "Python 3.9 or newer is required." >&2; exit 1; }
command -v rsync >/dev/null 2>&1 || warn "rsync is not installed: pulls will still work, but resuming large downloads needs rsync"
command -v tailscale >/dev/null 2>&1 || warn "Tailscale is not installed yet: https://tailscale.com/download"

step "Hermes Agent"
if command -v hermes >/dev/null 2>&1 || [[ -x "$HOME/.local/bin/hermes" ]]; then
  echo "found $(command -v hermes || echo "$HOME/.local/bin/hermes")"
elif [[ $INSTALL_HERMES -eq 1 ]]; then
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
  export PATH="$HOME/.local/bin:$PATH"
else
  warn "Hermes is not installed (--no-hermes). Install: curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash"
fi

step "fleet init"
# (the odd expansion keeps macOS bash 3.2 happy when no options were given)
python3 "$REPO_DIR/home/bin/fleet" init ${INIT_ARGS[@]+"${INIT_ARGS[@]}"}

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) warn "Add ~/.local/bin to your PATH (for example in ~/.bashrc or ~/.zshrc), then open a new terminal." ;;
esac

step "Done. Next steps"
cat <<'EOF'
1. Check the setup:
     fleet doctor
2. Give Hermes its API key and connect Telegram (docs/home/linux-macos.md, steps 4 and 5):
     hermes config set ANTHROPIC_API_KEY <your Claude Console key>
     hermes gateway setup
     hermes gateway install
     hermes gateway start
3. Create the scheduled checks:
     fleet hermes-cron
4. Then set up Tailscale and the VPSs: docs/getting-started.md, steps 2 to 6
   (online: https://coffeetimegx.github.io/hermes-fleet/getting-started/)
EOF
