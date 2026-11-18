#!/bin/bash
# Turns a stock ubuntu:24.04 container into something like a fresh Hostinger
# VPS: sshd running, the fleet key in root's authorized_keys. systemctl,
# hostnamectl, timedatectl, ufw and tailscale are replaced with test stubs
# (dpkg-divert keeps package installs from overwriting them).
set -euo pipefail
# docker exec can start with umask 0000; a real VPS login has 022, and sshd
# (with every session it starts) inherits this one.
umask 022
export DEBIAN_FRONTEND=noninteractive
S=/opt/fleet-test
for f in /usr/bin/systemctl /usr/bin/hostnamectl /usr/bin/timedatectl /usr/sbin/ufw; do
  dpkg-divert --local --rename --divert "$f.distrib" --add "$f" >/dev/null
  install -m 755 "$S/$(basename "$f")" "$f"
done
install -m 755 "$S/tailscale" /usr/bin/tailscale
apt-get update -q
apt-get install -y -q --no-install-recommends openssh-server >/dev/null
install -d -m 755 -o root -g root /run/sshd
install -d -m 700 -o root -g root /root/.ssh
ssh-keygen -A >/dev/null
install -m 600 "$S/authorized_keys" /root/.ssh/authorized_keys
/usr/sbin/sshd
echo "fake VPS ready: sshd running, root login with the fleet key"
