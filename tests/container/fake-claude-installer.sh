#!/bin/bash
# Stands in for https://claude.ai/install.sh in the container test: installs the
# Claude Code test stub as ~/.local/bin/claude.
set -euo pipefail
echo "fake Claude installer (channel ${1:-stable})"
install -D -m 755 /opt/fleet-test/claude-stub "$HOME/.local/bin/claude"
