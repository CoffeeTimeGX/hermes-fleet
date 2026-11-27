#!/usr/bin/env bash
# A fake Hostinger VPS for the whole provisioning path, over real SSH.
#
# A stock ubuntu:24.04 container gets sshd and the fleet key in root's
# authorized_keys, like a VPS created in hPanel with an SSH key. The fleet CLI
# then does what the docs tell the owner to do: fleet init, bootstrap --public,
# ping, provider install, secrets push, smoke check, dispatch, pull (rsync and
# tar), sync, restart, lockdown and its undo, and a bootstrap re-run. Only
# systemctl, ufw, tailscale, hostnamectl, timedatectl and the Claude installer
# are stand-ins (tests/container/), because a container has no init system, no
# firewall and no tailnet; everything else is the real thing, apt included.
#
# Needs docker, ssh, ssh-keygen, rsync, jq and python3. Takes a few minutes
# (the bootstrap installs ffmpeg and friends). Run: bash tests/vps-container.sh
# shellcheck disable=SC2015
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${FLEET_TEST_SSH_PORT:-2222}"
IMAGE="${FLEET_TEST_IMAGE:-ubuntu:24.04}"
NAME="fleet-fake-vps-$$"
T="$(mktemp -d)"
cleanup() {
  local rc=$?
  set +e
  if [[ $rc -ne 0 ]]; then
    echo "---- worker log on the fake VPS (last 40 lines)"
    docker exec "$NAME" tail -n 40 /home/fleet/fleet/logs/worker.log 2>/dev/null
    docker exec "$NAME" tail -n 20 /var/log/fleet-worker.out 2>/dev/null
  fi
  docker rm -f "$NAME" >/dev/null 2>&1
  rm -rf "$T"
}
trap cleanup EXIT

PASSES=0
pass() { PASSES=$((PASSES + 1)); printf '\033[32mPASS\033[0m %s\n' "$*"; }
fail() { printf '\033[31mFAIL\033[0m %s\n' "$*"; exit 1; }
has() { local pat="$1" out; shift; out="$("$@" 2>&1 || true)"; grep -q -- "$pat" <<<"$out"; }
wait_for() { local n="$1"; shift; for _ in $(seq 1 "$n"); do "$@" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }

export HOME="$T/home" FLEET_STATE_DIR="$T/state" FLEET_CONFIG="$T/fleet.ini"
mkdir -p "$HOME" "$T/bin"
# OpenSSH finds ~/.ssh through the password database, not $HOME. This wrapper
# keeps the fake VPS's host keys out of your real known_hosts file.
real_ssh="$(command -v ssh)"
cat >"$T/bin/ssh" <<EOF
#!/bin/sh
exec "$real_ssh" -o UserKnownHostsFile="$T/known_hosts" "\$@"
EOF
chmod 755 "$T/bin/ssh"
export PATH="$T/bin:$PATH"
cat >"$FLEET_CONFIG" <<EOF
[defaults]
results_dir = $T/results
secrets_dir = $T/secrets
ssh_key = $T/fleet_ed25519
connect_timeout = 10

[vps1]
; "Tailscale" and public address are both the container's port on this machine
host = 127.0.0.1
public_ip = 127.0.0.1
port = $PORT
hostinger_account = test account
EOF
F() { python3 "$REPO/home/bin/fleet" "$@"; }
VX() { docker exec "$NAME" "$@"; }                    # run on the fake VPS as root
# Capture, then grep: under pipefail, "VX cmd | grep -q" fails at random when
# grep stops reading before docker exec has written everything.
VO() { VX "$@" 2>/dev/null || true; }
J() { F jobs vps1 --json | jq -e "$@"; }
S() { F studio --json | jq -e "$@"; }   # S '<jq filter over one look of fleet studio>'

echo "== home machine: fleet init"
F init --no-hermes >"$T/init.txt"
grep -q "ssh-ed25519 " "$T/init.txt" && pass "init makes the fleet SSH key and prints it" || fail "init"
[[ -f "$T/secrets/vps1/claude.env" && -f "$T/secrets/tailscale.env" ]] && pass "init writes the secrets templates" || fail "secrets templates"
[[ "$(stat -c %a "$T/secrets")" == 700 ]] && pass "the secrets folder is private" || fail "secrets folder mode"
printf 'CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-test-token\nANTHROPIC_API_KEY=\n' >"$T/secrets/vps1/claude.env"
printf 'TS_AUTHKEY=tskey-auth-test\n' >"$T/secrets/tailscale.env"
chmod 600 "$T/secrets/vps1/claude.env" "$T/secrets/tailscale.env"

echo "== a fresh VPS (container $IMAGE)"
docker run -d --init --name "$NAME" --hostname srv1234567 -p "127.0.0.1:$PORT:22" "$IMAGE" sleep infinity >/dev/null
docker exec "$NAME" mkdir -p /opt/fleet-test
for f in "$REPO"/tests/container/*; do docker cp "$f" "$NAME:/opt/fleet-test/" >/dev/null; done
docker cp "$REPO/tests/lib/claude-stub" "$NAME:/opt/fleet-test/claude-stub" >/dev/null
docker cp "$T/fleet_ed25519.pub" "$NAME:/opt/fleet-test/authorized_keys" >/dev/null
VX bash /opt/fleet-test/prepare.sh
wait_for 20 F ping vps1 && fail "ping as fleet works before bootstrap" || pass "before bootstrap only root can log in"

echo "== bootstrap over the public address"
F bootstrap vps1 --public --skip-upgrade >"$T/bootstrap.txt" 2>&1 || { tail -n 60 "$T/bootstrap.txt"; fail "bootstrap"; }
pass "fleet bootstrap vps1 --public finished"
grep -q "worker: *active (version 1.8.0)" "$T/bootstrap.txt" && pass "bootstrap starts the worker" || fail "worker not active"
F ping vps1 >/dev/null && pass "the fleet user logs in with the key" || fail "ping"
[[ "$(VX cat /etc/hostname)" == vps1 ]] && pass "hostname set" || fail "hostname"
[[ "$(VO grep -c '^127\.0\.1\.1 vps1$' /etc/hosts)" == 1 ]] && pass "/etc/hosts names the node" || fail "/etc/hosts"
sshd_t="$(VO sshd -T)"
grep -qx "passwordauthentication no" <<<"$sshd_t" && pass "sshd: passwords off" || fail "passwordauthentication"
grep -qx "allowusers root" <<<"$sshd_t" && grep -qx "allowusers fleet" <<<"$sshd_t" \
  && pass "sshd: only root and fleet may log in" || fail "allowusers"
grep -q " L " <<<"$(VO passwd -S fleet)" && pass "the fleet user has no password" || fail "fleet password"
sudo_l="$(VO sudo -l -U fleet)"
grep -q "/usr/bin/systemctl restart fleet-worker" <<<"$sudo_l" && pass "fleet may only manage its own service" || fail "sudoers: $sudo_l"
grep -q "(ALL) ALL\|(root) ALL" <<<"$sudo_l" && fail "fleet has general sudo" || pass "fleet has no general sudo"
ufw_st="$(VO ufw status)"
grep -qE "^22/tcp +LIMIT" <<<"$ufw_st" && grep -q "on tailscale0" <<<"$ufw_st" \
  && pass "firewall: tailscale0 open, public SSH rate limited" || fail "ufw rules: $ufw_st"
[[ "$(VX tailscale status --json | jq -r .BackendState)" == Running ]] && pass "joined Tailscale with the auth key" || fail "tailscale"
VX grep -qx "MAX_PARALLEL=1" /etc/fleet/worker.env && pass "worker.env written" || fail "worker.env"
VX test -f /etc/logrotate.d/fleet-worker && pass "logrotate configured" || fail "logrotate"
VX test -f /etc/fail2ban/jail.d/fleet.conf && pass "fail2ban jail configured" || fail "fail2ban"
[[ "$(VX ps -o user= -p "$(VX cat /run/fleet-worker.pid)")" == fleet ]] && pass "the worker runs as the fleet user" || fail "worker user"
for tool in ffmpeg convert jq rsync git python3; do
  VX bash -c "command -v $tool" >/dev/null || fail "$tool missing"
done
pass "video and base tools installed (ffmpeg, imagemagick, jq, rsync, git, python3)"

echo "== provider: Claude Code"
F exec vps1 -- CLAUDE_INSTALLER=/opt/fleet-test/fake-claude-installer.sh \
  bash /home/fleet/fleet/app/providers/claude/install.sh stable >"$T/install.txt" 2>&1 || { cat "$T/install.txt"; fail "install.sh"; }
grep -q "Installed: 9.9.9" "$T/install.txt" && pass "install.sh installs Claude Code for the fleet user" || fail "install"
[[ "$(VX jq -r .env.DISABLE_AUTOUPDATER /home/fleet/.claude/settings.json)" == 1 ]] && pass "auto-updates are off" || fail "settings.json"
has "pushed CLAUDE_CODE_OAUTH_TOKEN" F secrets push claude vps1 && pass "secrets push sends only the filled-in token" || fail "secrets push"
[[ "$(VX stat -c '%U %a' /home/fleet/.config/fleet/providers/claude.env)" == "fleet 600" ]] && pass "the token file is private to fleet" || fail "token file mode"
VX grep -q ANTHROPIC_API_KEY /home/fleet/.config/fleet/providers/claude.env && fail "an empty API key was pushed" || pass "empty values are not pushed"
out="$(F provider check claude vps1 --smoke 2>&1 || true)"
grep -q "auth: oauth-token" <<<"$out" && grep -q "smoke: ok" <<<"$out" && pass "provider check --smoke passes" || fail "smoke: $out"
st="$(F status vps1 --json)"
jq -e '.[0].service == "active" and .[0].providers[0].ok and .[0].heartbeat_age_s >= 0' <<<"$st" >/dev/null \
  && pass "status over SSH: service active, claude ok, heartbeat" || fail "status: $st"

echo "== jobs over SSH"
VX bash -c 'printf "POLL_SECONDS=1\nLIMIT_MARGIN_SECONDS=1\n" >/etc/fleet/worker.local.env'
has "restarted" F restart vps1 && pass "fleet restart (sudo systemctl) works" || fail "restart"
id1="$(F dispatch --prompt "episode one" --channel "Space Facts" --json | jq -r '.[0].id')"
id2="$(F dispatch --prompt "LIMIT3 hits the usage limit" --channel "Space Facts" --json | jq -r '.[0].id')"
wait_for 90 J --arg a "$id1" --arg b "$id2" '[.[] | select((.id == $a or .id == $b) and .state == "done")] | length == 2' \
  || { F jobs vps1; fail "jobs did not finish"; }
pass "two jobs ran, one through a usage-limit hold"
J --arg b "$id2" '.[] | select(.id == $b) | .limit_waits == 1' >/dev/null && pass "the limited job waited and resumed" || fail "limit wait"
out="$(F pull)"
grep -q "Pulled 2 finished job(s)" <<<"$out" && pass "pull (rsync) downloads both jobs" || fail "pull: $out"
[[ -s "$T/results/vps1/$id1/output/video.txt" && -s "$T/results/vps1/$id2/logs/transcript.1.jsonl" ]] \
  && pass "results and the earlier attempt's transcript arrive" || fail "pulled files"
id3="$(F dispatch --prompt "episode three" --channel History --json | jq -r '.[0].id')"
wait_for 60 J --arg c "$id3" '.[] | select(.id == $c) | .state == "done"' || fail "job 3"
FLEET_PULL_METHOD=tar F pull >/dev/null && [[ -s "$T/results/vps1/$id3/output/SUMMARY.txt" ]] \
  && pass "pull (tar, as on Windows) works too" || fail "tar pull"
id4="$(F dispatch --prompt "SLEEP while the studio looks" --channel "Space Facts" --json | jq -r '.[0].id')"
wait_for 60 S --arg id "$id4" '.nodes[0].reachable and .nodes[0].activity[$id].detail == "Render the test video"' \
  && pass "studio over SSH shows what a running session does" || { F studio --json; fail "studio"; }
has "SIGTERM" F cancel vps1 "$id4" || fail "cancel the studio job"
wait_for 30 J --arg d "$id4" '.[] | select(.id == $d) | .state == "failed"' || fail "the studio job did not stop"

echo "== maintenance"
pid_before="$(VX cat /run/fleet-worker.pid)"
has "synced worker 1.8.0" F sync vps1 && pass "sync pushes the code" || fail "sync"
wait_for 10 bash -c "[[ \"\$(docker exec $NAME cat /run/fleet-worker.pid)\" != $pid_before ]]" \
  && pass "sync restarts the worker" || fail "worker not restarted"
[[ "$(F exec vps1 --root -- id -u | sed -n 2p)" == 0 ]] && pass "exec --root works" || fail "exec --root"

echo "== lockdown"
out="$(F lockdown vps1 2>&1 || true)"
grep -q "not a Tailscale address" <<<"$out" && pass "lockdown refuses over a non-Tailscale connection" || fail "lockdown guard: $out"
grep -qE "^22/tcp +LIMIT" <<<"$(VO ufw status)" || fail "public SSH rule vanished"
VX bash /home/fleet/fleet/app/lockdown.sh >/dev/null && pass "lockdown from a Tailscale session closes public SSH" || fail "lockdown"
grep -qE "^22(/tcp)?( \(v6\))? " <<<"$(VO ufw status)" && fail "a port 22 rule is still there" || pass "no port 22 rule left (IPv4 and IPv6)"
VX test -f /etc/fleet/locked-down && pass "lockdown is remembered" || fail "flag"
F bootstrap vps1 --skip-upgrade >"$T/bootstrap2.txt" 2>&1 || { tail -n 40 "$T/bootstrap2.txt"; fail "second bootstrap"; }
grep -q "public SSH stays closed" "$T/bootstrap2.txt" && ! grep -qE "^22/tcp " <<<"$(VO ufw status)" \
  && pass "a bootstrap re-run keeps public SSH closed" || fail "bootstrap reopened SSH"
[[ "$(VX grep -c "fleet_ed25519\|hermes-fleet@" /root/.ssh/authorized_keys)" == 1 ]] && pass "re-runs do not duplicate keys" || fail "duplicate keys"
[[ "$(VO grep -c '^127\.0\.1\.1 ' /etc/hosts)" == 1 ]] && pass "re-runs keep one /etc/hosts entry" || fail "/etc/hosts after a re-run"
has "public SSH re-opened" F lockdown vps1 --undo && grep -qE "^22/tcp +LIMIT" <<<"$(VO ufw status)" \
  && pass "lockdown --undo re-opens public SSH" || fail "undo"
F health >"$T/health.txt" || true
grep -qE "vps1: (fleet-worker|the worker loop|claude)" "$T/health.txt" && { cat "$T/health.txt"; fail "health"; }
pass "health shows no service, worker or provider problem"

echo "all $PASSES fake-VPS checks passed"
