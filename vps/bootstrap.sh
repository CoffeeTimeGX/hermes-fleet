#!/usr/bin/env bash
# One-time (and safely re-runnable) setup of a fresh Hostinger VPS as a fleet node.
#
# Run as root on Ubuntu 24.04 LTS (Hostinger's "Ubuntu 24.04" template; Debian 12
# also works). The home machine runs it for you:
#   fleet bootstrap <node> --public    first run, over the VPS's public IP
#   fleet bootstrap <node>             later re-runs, over Tailscale
# which uploads the repo's vps/ folder and calls this script with:
#
#   FLEET_NODE     node name, e.g. vps1                          (required)
#   FLEET_PUBKEY   the home machine's fleet SSH public key        (required)
#   TS_AUTHKEY     Tailscale auth key tagged tag:fleet            (first run)
#   MAX_PARALLEL   Claude sessions this node runs at once         (default 1)
#   FLEET_TZ       timezone, e.g. UTC or Europe/Madrid            (default UTC)
#   SWAP_GB        swap file size when RAM is under 8 GB         (default 4)
#   SKIP_UPGRADE   1 skips the full OS upgrade (quick re-runs)
#
# It updates the OS, installs base and video tooling, creates the unprivileged
# `fleet` user, hardens SSH (keys only), enables fail2ban, automatic security
# updates and the ufw firewall, joins your Tailscale network and installs the job
# worker as a systemd service. It does NOT install an LLM provider (that is
# `fleet provider install claude <node>`) and it does NOT close public SSH (that
# is `fleet lockdown <node>`, once SSH over Tailscale works).
set -euo pipefail
umask 022   # every file below gets an explicit mode; this covers the rest

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${FLEET_NODE:?set FLEET_NODE}"
: "${FLEET_PUBKEY:?set FLEET_PUBKEY}"
MAX_PARALLEL="${MAX_PARALLEL:-1}"
FLEET_TZ="${FLEET_TZ:-UTC}"
SWAP_GB="${SWAP_GB:-4}"
SKIP_UPGRADE="${SKIP_UPGRADE:-0}"
FLEET_USER=fleet
FLEET_HOME=/home/$FLEET_USER
FLEET_ROOT=$FLEET_HOME/fleet
APT=(apt-get -y -o DPkg::Lock::Timeout=600 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$*"; }
fail() { printf '\033[31mbootstrap: %s\033[0m\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || fail "must run as root"
[[ "$FLEET_NODE" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || fail "FLEET_NODE must be a lowercase hostname like vps1"
[[ "$FLEET_PUBKEY" =~ ^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521))\ [A-Za-z0-9+/=]+(\ .*)?$ ]] \
  || fail "FLEET_PUBKEY does not look like an SSH public key"
[[ "$MAX_PARALLEL" =~ ^[1-9][0-9]?$ ]] || fail "MAX_PARALLEL must be a number from 1 to 99"
[[ "$SWAP_GB" =~ ^[0-9]{1,3}$ ]] || fail "SWAP_GB must be a whole number"
# shellcheck disable=SC1091
. /etc/os-release
[[ "${ID:-}" == "ubuntu" || "${ID:-}" == "debian" ]] || fail "Ubuntu or Debian only (found ${ID:-unknown})"
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1

step "Hostname and timezone"
hostnamectl set-hostname "$FLEET_NODE"
# Keep the name across reboots on images where cloud-init would reset it.
if [[ -d /etc/cloud/cloud.cfg.d ]]; then
  echo 'preserve_hostname: true' >/etc/cloud/cloud.cfg.d/99-fleet-hostname.cfg
fi
# Rewrite /etc/hosts in place rather than with `sed -i`, which replaces the file
# and fails where /etc/hosts is a mount point.
hosts="$(awk -v n="$FLEET_NODE" '/^127\.0\.1\.1[[:space:]]/ { if (!done) print "127.0.1.1 " n; done = 1; next }
                                 { print } END { if (!done) print "127.0.1.1 " n }' /etc/hosts)"
printf '%s\n' "$hosts" >/etc/hosts
if [[ -e "/usr/share/zoneinfo/$FLEET_TZ" ]]; then
  timedatectl set-timezone "$FLEET_TZ" || warn "could not set timezone $FLEET_TZ"
else
  warn "unknown timezone '$FLEET_TZ', keeping $(cat /etc/timezone 2>/dev/null || echo the current one)"
fi

step "OS updates and packages"
"${APT[@]}" update
if [[ "$SKIP_UPGRADE" == "1" ]]; then
  echo "skipped the full upgrade (SKIP_UPGRADE=1)"
else
  "${APT[@]}" upgrade
fi
"${APT[@]}" install --no-install-recommends \
  ca-certificates curl wget git jq rsync tmux htop unzip zip tar procps util-linux coreutils sudo openssh-server \
  bsdextrautils logrotate ufw fail2ban python3-systemd unattended-upgrades needrestart \
  python3 python3-venv python3-pip build-essential \
  ffmpeg imagemagick fonts-dejavu fonts-liberation fonts-noto-color-emoji

step "Journal size cap (keeps logs from filling the disk)"
install -d /etc/systemd/journald.conf.d
cat >/etc/systemd/journald.conf.d/90-fleet.conf <<'EOF'
[Journal]
SystemMaxUse=500M
EOF
systemctl restart systemd-journald || true

step "Swap (only when RAM is under 8 GB and there is no swap yet)"
mem_gb=$(awk '/MemTotal/{print int($2/1024/1024)}' /proc/meminfo)
if [[ "$mem_gb" -lt 8 && -z "$(swapon --show --noheadings 2>/dev/null)" && "$SWAP_GB" -gt 0 ]]; then
  if fallocate -l "${SWAP_GB}G" /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile; then
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
    echo 'vm.swappiness=10' >/etc/sysctl.d/90-fleet-swap.conf
    sysctl -q -p /etc/sysctl.d/90-fleet-swap.conf || true
    echo "created a ${SWAP_GB} GB swap file"
  else
    swapoff /swapfile 2>/dev/null || true
    rm -f /swapfile
    warn "could not create a swap file on this server; continuing without swap"
  fi
else
  echo "skipped (RAM about ${mem_gb} GB, swap devices: $(swapon --show --noheadings 2>/dev/null | wc -l))"
fi

step "fleet user and SSH keys"
id "$FLEET_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$FLEET_USER"
passwd -l "$FLEET_USER" >/dev/null 2>&1 || true
for home in "$FLEET_HOME" /root; do
  install -d -m 700 "$home/.ssh"
  touch "$home/.ssh/authorized_keys"
  grep -qxF "$FLEET_PUBKEY" "$home/.ssh/authorized_keys" || echo "$FLEET_PUBKEY" >>"$home/.ssh/authorized_keys"
  chmod 600 "$home/.ssh/authorized_keys"
done
chown -R "$FLEET_USER:$FLEET_USER" "$FLEET_HOME/.ssh"

# The fleet user may only manage its own worker service: no general sudo.
cat >/etc/sudoers.d/fleet <<'EOF'
fleet ALL=(root) NOPASSWD: /usr/bin/systemctl restart fleet-worker, /usr/bin/systemctl start fleet-worker, /usr/bin/systemctl stop fleet-worker, /usr/bin/systemctl status fleet-worker
EOF
chmod 440 /etc/sudoers.d/fleet
visudo -cf /etc/sudoers.d/fleet >/dev/null

step "SSH hardening (keys only, no passwords)"
cat >/etc/ssh/sshd_config.d/10-fleet.conf <<'EOF'
# Managed by hermes-fleet bootstrap.sh. sshd uses the first value it reads, and
# this file is read before 50-cloud-init.conf, so these settings win.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
ClientAliveInterval 60
ClientAliveCountMax 5
AllowUsers root fleet
EOF
sshd -t
systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true

step "fail2ban and automatic security updates"
cat >/etc/fail2ban/jail.d/fleet.conf <<'EOF'
[sshd]
enabled = true
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
ignoreip = 127.0.0.1/8 ::1 100.64.0.0/10
EOF
systemctl enable fail2ban >/dev/null 2>&1 || true
systemctl restart fail2ban || warn "fail2ban did not start; check: journalctl -u fail2ban"
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

step "Tailscale (the private network to your home machine)"
if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled >/dev/null
ts_state() { tailscale status --json 2>/dev/null | jq -r '.BackendState // ""' 2>/dev/null || true; }
if [[ "$(ts_state)" == "Running" ]]; then
  # Already joined: never re-run `tailscale up` here, because a re-run over
  # Tailscale could cut the connection this script is running through.
  tailscale set --hostname="$FLEET_NODE" --accept-dns=false || true
  echo "already on Tailscale as $(tailscale ip -4 2>/dev/null | head -n1)"
elif [[ -n "${TS_AUTHKEY:-}" ]]; then
  tailscale up --reset --auth-key="$TS_AUTHKEY" --hostname="$FLEET_NODE" --accept-dns=false
  echo "joined Tailscale as $(tailscale ip -4 2>/dev/null | head -n1)"
else
  warn "no TS_AUTHKEY: fill in tailscale.env on the home machine and re-run fleet bootstrap $FLEET_NODE --public"
fi

step "Firewall (ufw)"
if ufw status | grep -q 'Status: inactive'; then
  ufw --force reset >/dev/null
fi
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow in on tailscale0 >/dev/null
ufw allow 41641/udp >/dev/null
if [[ -f /etc/fleet/locked-down ]]; then
  echo "public SSH stays closed (this node was locked down earlier)"
else
  ufw limit 22/tcp >/dev/null
fi
ufw --force enable >/dev/null
ufw status | sed -n '1,30p'

step "Worker files"
install -d -o "$FLEET_USER" -g "$FLEET_USER" "$FLEET_ROOT" "$FLEET_ROOT/app" \
  "$FLEET_ROOT/jobs" "$FLEET_ROOT/work" "$FLEET_ROOT/logs" "$FLEET_HOME/.config" "$FLEET_HOME/.config/fleet"
install -d -m 700 -o "$FLEET_USER" -g "$FLEET_USER" "$FLEET_HOME/.config/fleet/providers"
rsync -a --delete --exclude '*.env' "$SRC_DIR/" "$FLEET_ROOT/app/"
chown -R "$FLEET_USER:$FLEET_USER" "$FLEET_ROOT/app"
chmod 755 "$FLEET_ROOT/app/worker/fleet-worker"
ln -sf "$FLEET_ROOT/app/worker/fleet-worker" /usr/local/bin/fleet-worker
install -m 644 "$SRC_DIR/logrotate/fleet-worker" /etc/logrotate.d/fleet-worker

install -d -m 755 /etc/fleet
cat >/etc/fleet/worker.env <<EOF
# Managed by hermes-fleet bootstrap.sh: change "sessions" in fleet.ini on the
# home machine and re-run fleet bootstrap $FLEET_NODE. For local overrides,
# create /etc/fleet/worker.local.env (same format), then: systemctl restart fleet-worker
FLEET_NODE=$FLEET_NODE
FLEET_ROOT=$FLEET_ROOT
MAX_PARALLEL=$MAX_PARALLEL
POLL_SECONDS=5
DEFAULT_TIMEOUT_MINUTES=180
DEFAULT_MAX_RETRIES=1
MIN_FREE_GB=3
GC_DAYS=7
HOME=$FLEET_HOME
EOF
chmod 644 /etc/fleet/worker.env

step "systemd services"
install -m 644 "$SRC_DIR/systemd/fleet-worker.service" /etc/systemd/system/fleet-worker.service
install -m 644 "$SRC_DIR/systemd/fleet-gc.service" /etc/systemd/system/fleet-gc.service
install -m 644 "$SRC_DIR/systemd/fleet-gc.timer" /etc/systemd/system/fleet-gc.timer
systemctl daemon-reload
systemctl enable fleet-worker.service fleet-gc.timer >/dev/null 2>&1
systemctl restart fleet-worker.service
systemctl start fleet-gc.timer

step "Done"
cat <<EOF
node:          $FLEET_NODE
tailscale:     $(tailscale ip -4 2>/dev/null | head -n1 || true) ($(ts_state))
worker:        $(systemctl is-active fleet-worker) (version $("$FLEET_ROOT/app/worker/fleet-worker" version))
parallel jobs: $MAX_PARALLEL
public ssh:    $([[ -f /etc/fleet/locked-down ]] && echo closed || echo 'open, keys only and rate limited, until fleet lockdown')
reboot needed: $([[ -f /var/run/reboot-required ]] && echo 'yes (fleet reboot from the home machine)' || echo no)
next:          fleet ping $FLEET_NODE, then fleet lockdown $FLEET_NODE, then fleet provider install claude $FLEET_NODE
EOF
