#!/usr/bin/env bash
# Close public SSH on a fleet node so it can only be reached over Tailscale.
#
#   fleet lockdown <node>           from the home machine, over Tailscale
#   fleet lockdown <node> --undo    re-open public SSH (keys only, rate limited)
#
# Locked out? Open the VPS in Hostinger hPanel, click "Web console" on the
# Overview page, and run:  bash /home/fleet/fleet/app/lockdown.sh --undo
set -euo pipefail
umask 022
[[ "$(id -u)" -eq 0 ]] || { echo "lockdown.sh must run as root" >&2; exit 1; }
FLAG=/etc/fleet/locked-down

public_ssh_rules() { ufw status | grep -E '^(22|22/tcp|OpenSSH)( \(v6\))?[[:space:]]+(ALLOW|LIMIT)' || true; }

if [[ "${1:-}" == "--undo" ]]; then
  ufw limit 22/tcp >/dev/null
  rm -f "$FLAG"
  echo "public SSH re-opened (keys only, rate limited)"
  ufw status
  exit 0
fi

state="$(tailscale status --json 2>/dev/null | jq -r '.BackendState // ""' 2>/dev/null || true)"
ip4="$(tailscale ip -4 2>/dev/null | head -n1 || true)"
if [[ "$state" != "Running" || -z "$ip4" ]]; then
  echo "Tailscale is not running on this node (state: ${state:-unknown}); refusing to close public SSH." >&2
  exit 1
fi
if [[ -n "${SSH_CONNECTION:-}" ]]; then
  client_ip="${SSH_CONNECTION%% *}"
  # Tailscale addresses: 100.64.0.0/10 and fd7a:115c:a1e0::/48
  if ! [[ "$client_ip" =~ ^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\. || "$client_ip" =~ ^fd7a:115c:a1e0: ]]; then
    echo "You are connected from $client_ip, which is not a Tailscale address." >&2
    echo "Reconnect over Tailscale first (fleet ping $(hostname -s) must work without --public)." >&2
    exit 1
  fi
fi

ufw allow in on tailscale0 >/dev/null
for rule in "limit 22/tcp" "allow 22/tcp" "allow 22" "allow OpenSSH"; do
  # shellcheck disable=SC2086
  ufw --force delete $rule >/dev/null 2>&1 || true
done
if [[ -n "$(public_ssh_rules)" ]]; then
  echo "Could not remove every public SSH rule; remove these by hand (ufw status numbered):" >&2
  public_ssh_rules >&2
  exit 1
fi
install -d /etc/fleet
date -u +%FT%TZ >"$FLAG"
echo "public SSH closed: this node is reachable only over Tailscale ($ip4)"
ufw status
