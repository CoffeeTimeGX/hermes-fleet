#!/usr/bin/env bash
# End-to-end test of the fleet CLI, the VPS worker and the Claude adapter on one
# machine. Three fake VPSs are folders, SSH is replaced by the CLI's local
# transport and Claude Code by tests/lib/claude-stub. No network, no root, no
# real accounts. Needs: bash, jq, python3, tar, flock, setsid, timeout, pkill.
# `pass` never fails and `fail` always exits, so "A && pass || fail" is safe here.
# shellcheck disable=SC2015
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"
WORKER_PIDS=()
cleanup() {
  set +e   # a worker that is already gone must not stop the cleanup half way
  local p
  for p in "${WORKER_PIDS[@]:-}"; do [[ -n "$p" ]] && kill "$p" 2>/dev/null; done
  pkill -f -- "$T/nodes/" 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do pgrep -f -- "$T/nodes/" >/dev/null || break; sleep 1; done
  pkill -KILL -f -- "$T/nodes/" 2>/dev/null
  wait 2>/dev/null
  rm -rf "$T"
}
trap cleanup EXIT

PASSES=0
pass() { PASSES=$((PASSES + 1)); printf '\033[32mPASS\033[0m %s\n' "$*"; }
fail() { printf '\033[31mFAIL\033[0m %s\n' "$*"; exit 1; }
check() { local what="$1"; shift; if "$@" >/dev/null 2>&1; then pass "$what"; else fail "$what"; fi; }
wait_for() { local n="$1"; shift; for _ in $(seq 1 "$n"); do "$@" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
# has PATTERN CMD...: run CMD (whatever its exit code) and grep its stdout and stderr.
# Capturing first avoids pipefail and SIGPIPE surprises from "CMD | grep -q".
has() { local pat="$1" out; shift; out="$("$@" 2>&1 || true)"; grep -q -- "$pat" <<<"$out"; }

export HOME="$T/home" FLEET_IGNORE_ENV_FILES=1 FLEET_STATE_DIR="$T/state" LIMIT_MARGIN_SECONDS=1
mkdir -p "$HOME" "$T/bin" "$T/secrets"/{vps1,vps2,vps3} "$T/jobs"
install -m 755 "$REPO/tests/lib/claude-stub" "$T/bin/claude"
export PATH="$T/bin:$PATH"

cat >"$T/fleet.ini" <<EOF
[defaults]
transport = local
remote_root = $T/nodes/{node}
results_dir = $T/results
secrets_dir = $T/secrets
ssh_key = $T/no-key
[vps1]
host = vps1
[vps2]
host = vps2
[vps3]
host = vps3
EOF
export FLEET_CONFIG="$T/fleet.ini"
F() { python3 "$REPO/home/bin/fleet" --config "$T/fleet.ini" "$@"; }
J() { F jobs --json | jq -e "$@"; }   # J '<jq filter over all jobs>'
S() { F studio --json | jq -e "$@"; }  # S '<jq filter over one look of fleet studio>'
state_of() { F jobs --json | jq -r --arg id "$1" '.[] | select(.id == $id) | .state'; }
start_worker() {
  local n="$1"; shift
  env FLEET_ROOT="$T/nodes/$n" FLEET_NODE="$n" POLL_SECONDS=1 "$@" "$T/nodes/$n/app/worker/fleet-worker" loop &
  WORKER_PIDS+=("$!")
}

echo "== inventory, code and credentials"
check "list shows the inventory" bash -c "python3 '$REPO/home/bin/fleet' --config '$T/fleet.ini' list | grep -q vps3"
[[ "$(F sync | grep -c 'synced worker 1.4.0')" == 3 ]] && pass "sync installs the worker on all 3 nodes" || fail "sync"
for n in vps1 vps2 vps3; do printf 'ANTHROPIC_API_KEY=sk-test\n# CLAUDE_CODE_OAUTH_TOKEN=\n' >"$T/secrets/$n/claude.env"; done
chmod 600 "$T"/secrets/*/claude.env
chmod 644 "$T/secrets/vps1/claude.env"
if F secrets push claude vps1 >/dev/null 2>&1; then fail "pushed a world-readable secrets file"; fi
pass "secrets push refuses a world-readable secrets file"
chmod 600 "$T/secrets/vps1/claude.env"
[[ "$(F secrets push claude all | grep -c 'pushed ANTHROPIC_API_KEY')" == 3 ]] && pass "secrets push (only filled-in values)" || fail "secrets push"
[[ "$(stat -c %a "$HOME/.config/fleet/providers/claude.env")" == 600 ]] && pass "pushed credentials are private (600)" || fail "permissions"
check "push time is recorded for the token-age check" test -s "$HOME/.config/fleet/providers/.claude.pushed"

echo "== workers"
start_worker vps1 MAX_PARALLEL=2
start_worker vps2
start_worker vps3 MIN_FREE_GB=999999
check "workers write heartbeats" wait_for 10 test -s "$T/nodes/vps3/.heartbeat"
F status >"$T/status.txt"
check "status shows claude ok" grep -Eq '^vps1 +unknown .*claude:ok' "$T/status.txt"
check "status --json flags vps3 as low on disk" bash -c \
  "python3 '$REPO/home/bin/fleet' --config '$T/fleet.ini' status --json | jq -e '.[] | select(.node==\"vps3\") | .low_disk'"
check "health reports the low disk" bash -c "python3 '$REPO/home/bin/fleet' --config '$T/fleet.ini' health | grep -q 'vps3: low disk'"

echo "== dispatch"
id1="$(F dispatch --prompt "episode one" --channel "Space Facts" --to vps1 --json | jq -r '.[0].id')"
[[ "$id1" =~ ^[0-9]{8}-[0-9]{6}-space-facts-[a-z0-9]{5}$ ]] && pass "job ids are readable ($id1)" || fail "job id $id1"
out="$(F dispatch --prompt "episode two" --channel History)"
[[ "$out" =~ on\ vps[12]\  ]] && pass "auto dispatch avoids the low-disk node" || fail "auto dispatch: $out"
id2="$(awk '{print $2}' <<<"$out")"
fail_id="$(F dispatch --prompt "please FAIL" --channel History --to vps2 --json | jq -r '.[0].id')"
slow_id="$(F dispatch --prompt "long SLEEP" --channel Slow --to vps1 --json | jq -r '.[0].id')"
mkdir -p "$T/nodes/vps2/app/templates/demo"
echo "channel style rules" >"$T/nodes/vps2/app/templates/demo/CLAUDE.md"
cat >"$T/jobs/files.json" <<'EOF'
{"channel": "Demo", "title": "files test", "template": "demo", "prompt": "LIST the workspace",
 "effort": "high", "max_turns": 42, "max_budget_usd": 2.5,
 "files": [{"path": "brief/notes.md", "content": "hello"},
           {"path": "img/pixel.bin", "content": "aGk=", "encoding": "base64"}]}
EOF
files_id="$(F dispatch "$T/jobs/files.json" --to vps2 --json | jq -r '.[0].id')"
before="$(find "$T/nodes" -path '*/jobs/*' -name '*.json' | wc -l)"
F dispatch --prompt "x" --channel y --dry-run | jq -e -s '.[0].node and .[0].id' >/dev/null && pass "dry run prints the job" || fail "dry run"
[[ "$(find "$T/nodes" -path '*/jobs/*' -name '*.json' | wc -l)" == "$before" ]] && pass "dry run queues nothing" || fail "dry run queued"
echo '{"prompt": "x", "files": [{"path": "../evil", "content": "x"}]}' >"$T/jobs/bad1.json"
has "unsafe" F dispatch "$T/jobs/bad1.json" && pass "dispatch refuses unsafe file paths" || fail "unsafe path accepted"
echo '{"prompt": "x", "effort": "turbo"}' >"$T/jobs/bad2.json"
has '"effort" must be one of' F dispatch "$T/jobs/bad2.json" && pass "dispatch validates effort" || fail "effort"
echo "{\"id\": \"$id1\", \"prompt\": \"again\"}" >"$T/jobs/dup.json"
if F dispatch "$T/jobs/dup.json" --to vps1 >/dev/null 2>&1; then fail "duplicate id accepted"; fi
pass "duplicate job ids are refused"
cat >"$T/nodes/vps1/jobs/inbox/sneaky.json" <<'EOF'
{"prompt": "x", "files": [{"path": "../../outside.txt", "content": "pwned"}]}
EOF

echo "== results"
wait_for 60 J --arg a "$id1" --arg b "$id2" --arg c "$fail_id" --arg d "$files_id" \
  '[.[] | select((.id == $a or .id == $b or .id == $c or .id == $d or .id == "sneaky") and (.state == "done" or .state == "failed"))] | length == 5' \
  || { F jobs; fail "jobs did not finish"; }
pass "5 jobs finished"
check "a failing session is filed as failed" J --arg id "$fail_id" '.[] | select(.id == $id) | .state == "failed" and (.reason | test("exited 1"))'
check "a job with an unsafe path is rejected on the VPS too" J '.[] | select(.id == "sneaky") | .state == "failed" and (.reason | test("bad job"))'
check "nothing was written outside the workspace" test ! -e "$T/nodes/vps1/outside.txt"
out="$(F pull)"
grep -q "Pulled 5 finished job(s)" <<<"$out" && pass "pull downloads all finished jobs" || { echo "$out"; fail "pull"; }
grep -q "\[FAILED\] vps2/$fail_id" <<<"$out" && pass "pull reports failures" || fail "pull failure line"
check "outputs land in results_dir" test -s "$T/results/vps1/$id1/output/video.txt"
check "the session summary is saved" grep -q "Rendered 1 video for: episode one" "$T/results/vps1/$id1/output/SUMMARY.txt"
check "result.json comes from the stream (non-JSON lines skipped)" jq -e '.num_turns == 3' "$T/results/vps1/$id1/result.json"
check "template files reach the workspace" grep -qx './CLAUDE.md' "$T/results/vps2/$files_id/output/files.txt"
check "job files reach the workspace" grep -qx './brief/notes.md' "$T/results/vps2/$files_id/output/files.txt"
check "base64 job files are decoded" bash -c "[[ \$(cat '$T/nodes/vps2/work/$files_id/img/pixel.bin') == hi ]]"
args="$T/results/vps2/$files_id/logs/stub-args.txt"
check "job options reach Claude Code (effort, max turns, budget, mode)" bash -c \
  "grep -qx high '$args' && grep -qx 42 '$args' && grep -qx 2.5 '$args' && grep -qx bypassPermissions '$args'"
check "the job temp folder is cleaned up" test ! -e "$T/nodes/vps2/work/$files_id/.tmp"
check "pull writes an index" bash -c "[[ \$(wc -l <'$T/results/index.jsonl') -ge 5 ]]"
[[ -z "$(F pull --quiet)" ]] && pass "a second pull is silent" || fail "second pull not silent"
check "jobs are marked as pulled" J --arg id "$id1" '.[] | select(.id == $id) | .pulled'
check "logs shows the provider log" bash -c "python3 '$REPO/home/bin/fleet' --config '$T/fleet.ini' logs vps1 '$id1' | grep -q 'claude: finished'"

echo "== cancel and retry"
wait_for 20 J --arg id "$slow_id" '.[] | select(.id == $id) | .state == "running"' || fail "slow job never started"
wait_for 10 S --arg id "$slow_id" '.nodes[] | select(.name == "vps1") | .activity[$id].detail == "Render the test video"' \
  && pass "fleet studio shows what a running session does" || fail "studio activity"
S '[.nodes[] | select(.reachable)] | length == 3 and all(.[]; .status.queue and (.jobs | type == "array"))' >/dev/null \
  && pass "fleet studio looks at every VPS" || fail "studio snapshot"
has "SIGTERM" F cancel vps1 "$slow_id" && pass "cancel signals a running job" || fail "cancel"
wait_for 20 J --arg id "$slow_id" '.[] | select(.id == $id) | .state == "failed" and .reason == "cancelled"' \
  && pass "a cancelled job is filed as cancelled" || fail "cancel not recorded"
has "queued $fail_id-r1 on vps2" F retry vps2 "$fail_id" && pass "retry queues a copy" || fail "retry"
wait_for 20 J --arg id "$fail_id-r1" '.[] | select(.id == $id) | .state == "failed"' || fail "retry did not run"
has "queued $fail_id-r2 on vps1" F retry vps2 "$fail_id-r1" --to vps1 && pass "retrying a retry counts up, --to moves it" || fail "retry 2"

echo "== pause and resume"
has "paused" F pause vps2 --reason "maintenance" && pass "pause" || fail "pause"
pid_job="$(F dispatch --prompt "after pause" --channel History --to vps2 --json 2>"$T/warn.txt" | jq -r '.[0].id')"
check "dispatching to a paused node warns" grep -q "vps2: paused" "$T/warn.txt"
sleep 3
[[ "$(state_of "$pid_job")" == "inbox" ]] && pass "a paused node starts nothing" || fail "paused node ran a job"
check "health reports the pause" bash -c "python3 '$REPO/home/bin/fleet' --config '$T/fleet.ini' health | grep -q 'vps2: paused'"
has " on vps1 " F dispatch --prompt "auto while paused" --channel x && pass "auto dispatch avoids the paused node" || fail "auto vs paused"
has "resumed" F resume vps2 && pass "resume" || fail "resume"
wait_for 20 J --arg id "$pid_job" '.[] | select(.id == $id) | .state == "done"' && pass "queued work starts after resume" || fail "after resume"

echo "== usage limits (subscription accounts)"
lim_id="$(F dispatch --prompt "LIMIT30 long job" --channel Limits --to vps2 --json | jq -r '.[0].id')"
check "a usage limit puts the node on hold" wait_for 20 test -s "$T/nodes/vps2/.limit"
check "the job goes back in the queue" J --arg id "$lim_id" \
  '.[] | select(.id == $id) | .state == "inbox" and .limit_waits == 1 and (.reason | test("usage limit"))'
check "status --json shows the hold and its reset time" bash -c \
  "python3 '$REPO/home/bin/fleet' --config '$T/fleet.ini' status --json | jq -e '.[] | select(.node==\"vps2\") | .limit.kind == \"five_hour\" and .limit.until > now'"
has "LIMIT until" F status && pass "status shows the hold" || fail "status hold"
has " on vps1 " F dispatch --prompt "auto while limited" --channel x && pass "auto dispatch avoids a node at its usage limit" || fail "auto vs limit"
if has "usage limit" F health; then fail "a 5-hour limit was reported as a health problem"; fi
pass "a routine 5-hour limit is not a health problem"
now_s="$(date +%s)"
jq -n --argjson s "$now_s" --argjson u "$((now_s + 5 * 86400))" \
  '{provider:"claude", kind:"seven_day", message:"You have hit your weekly limit", since:$s, until:$u, until_iso:"x", job:"x"}' \
  >"$T/nodes/vps1/.limit"
has "vps1: claude usage limit reached (You have hit your weekly limit)" F health \
  && pass "health reports a weekly limit" || fail "weekly limit in health"
out="$(F dispatch --prompt "everyone is limited" --channel x 2>&1)"
grep -q " on vps2 " <<<"$out" && grep -q "at its usage limit" <<<"$out" \
  && pass "with every account limited, dispatch queues where the limit ends first" || fail "all limited: $out"
has "usage-limit hold ended early" F resume vps1,vps2 && pass "resume ends a usage-limit hold early" || fail "resume limit"
wait_for 30 J --arg id "$lim_id" '.[] | select(.id == $id) | .state == "done"' \
  && pass "the job resumes its Claude session and finishes" || fail "limited job did not finish"
check "the session was resumed, not restarted" grep -qx -- --resume "$T/nodes/vps2/work/$lim_id/logs/stub-args.txt"
check "the first attempt's transcript is kept" test -s "$T/nodes/vps2/work/$lim_id/logs/transcript.1.jsonl"
check "a usage limit does not use up a retry" J --arg id "$lim_id" '.[] | select(.id == $id) | .attempts == 1 and .limit_waits == 1'
lim2="$(F dispatch --prompt "LIMIT2 short job" --channel Limits --to vps2 --json | jq -r '.[0].id')"
wait_for 30 J --arg id "$lim2" '.[] | select(.id == $id) | .state == "done" and .limit_waits == 1' \
  && pass "the hold ends by itself when the limit resets" || fail "limit expiry"
check "no hold is left behind" test ! -e "$T/nodes/vps2/.limit"

echo "== one channel per VPS, and handover"
cat >"$T/fleet-ch.ini" <<EOF
[defaults]
transport = local
remote_root = $T/nodes/{node}
results_dir = $T/results
secrets_dir = $T/secrets
ssh_key = $T/no-key
[vps1]
host = vps1
channels = Space Facts
[vps2]
host = vps2
channels = History, all
[vps3]
host = vps3
channels =
EOF
FC() { python3 "$REPO/home/bin/fleet" --config "$T/fleet-ch.ini" "$@"; }
W1="$T/nodes/vps1" W2="$T/nodes/vps2"
has " on vps1 " FC dispatch --prompt "own channel" --channel "space facts" \
  && pass "a channel's job goes to its own VPS (names match loosely)" || fail "channel dispatch"
has " on vps2 " FC dispatch --prompt "shared" --channel Cooking \
  && pass "a channel without a VPS of its own goes to one with channels = all" || fail "channels = all"
F pause vps1 >/dev/null
sf_id="$(FC dispatch --prompt "waits for its VPS" --channel "Space Facts" --json 2>"$T/warn.txt" | jq -r '.[0].id')"
check "a channel's job is queued on its own VPS even when it is paused" grep -q "vps1: paused" "$T/warn.txt"
[[ "$(state_of "$sf_id")" == "inbox" ]] && pass "and nothing moves it to another VPS" || fail "the job moved by itself"
mkdir -p "$W1/work/half1/output"
echo "half a video" >"$W1/work/half1/output/part.txt"
echo '{"id": "half1", "state": "waiting", "attempts": 0, "limit_waits": 1}' >"$W1/work/half1/status.json"
echo '{"prompt": "half done", "channel": "Space Facts"}' >"$W1/jobs/inbox/half1.json"
out="$(FC handover vps1 vps2 --dry-run)"
grep -q "would move $sf_id" <<<"$out" && grep -q "would move half1" <<<"$out" && [[ -f "$W1/jobs/inbox/half1.json" ]] \
  && pass "handover --dry-run lists the queued jobs and moves nothing" || fail "dry run: $out"
out="$(FC handover vps1 vps2 2>&1)"
grep -q "moved $sf_id (channel Space Facts) from vps1 to vps2" <<<"$out" && pass "handover moves the queued jobs" || fail "handover: $out"
grep -q "it had started on vps1, so it starts over on vps2" <<<"$out" && pass "handover says when a job starts over" || fail "$out"
grep -q "note: only these jobs moved" <<<"$out" && pass "handover says the channel keeps its VPS" || fail "$out"
wait_for 30 J --arg id "$sf_id" '.[] | select(.id == $id) | .node == "vps2" and .state == "done"' \
  && pass "a handed-over job runs on the new VPS" || fail "handed-over job"
check "nothing of it is left on the old VPS" bash -c "! ls '$W1'/jobs/*/'$sf_id'.json"
check "the job says where it came from" jq -e '.handed_over_from == "vps1" and .node == "vps2"' "$W2/jobs/done/$sf_id.json"
check "a job that had started is filed as moved on the old VPS" \
  J '.[] | select(.id == "half1" and .node == "vps1") | .state == "moved" and (.reason | test("handed over to vps2"))'
wait_for 30 J '.[] | select(.id == "half1" and .node == "vps2") | .state == "done"' \
  && pass "and it starts over on the new one" || fail "half1 on vps2"
out="$(F pull)"
grep -q "\[MOVED\] vps1/half1" <<<"$out" && [[ -s "$T/results/vps1/half1/output/part.txt" ]] \
  && pass "pull brings home what a job made before it moved" || fail "pull after handover: $out"
bh="$(F dispatch --prompt "broken handover" --channel "Space Facts" --to vps1 --json 2>/dev/null | jq -r '.[0].id')"
env FLEET_ROOT="$W1" FLEET_NODE=vps1 "$W1/app/worker/fleet-worker" release "$bh" vps2 >"$T/bh.json"
check "a handover that stopped halfway shows in fleet jobs" \
  J --arg id "$bh" '.[] | select(.id == $id) | .state == "outgoing" and .reason == "being handed over to vps2"'
touch -d '-11 minutes' "$W1/jobs/outgoing/$bh.json"
has "1 job(s) stopped halfway through a handover" F health && pass "health reports it" || fail "stuck handover in health"
has "halfway through a handover to vps2" FC handover vps1 vps3 "$bh" \
  && pass "meanwhile it cannot be handed to a third VPS" || fail "third VPS"
jq -c '. + {node: "vps2", handed_over_from: "vps1", handed_over_at: .handover.at} | del(.handover)' "$T/bh.json" \
  >"$W2/jobs/inbox/$bh.json"
has "moved $bh" FC handover vps1 vps2 "$bh" && pass "running the same handover again finishes it" || fail "finish handover"
[[ "$(find "$T/nodes" -path '*/jobs/*' -name "$bh.json" | wc -l)" == 1 ]] && pass "without a second copy" || fail "two copies"
F pause vps2 >/dev/null
dup="$(F dispatch --prompt "name clash" --channel History --to vps2 --json 2>/dev/null | jq -r '.[0].id')"
mkdir -p "$W1/work/$dup" && echo '{"prompt": "an older job with the same id"}' >"$W1/jobs/done/$dup.json"
has "as $dup-h1" FC handover vps2 vps1 "$dup" && pass "a job whose id is taken on the new VPS gets a new one" || fail "rename"
check "the renamed job waits there" J --arg id "$dup-h1" '.[] | select(.id == $id) | .node == "vps1" and .state == "inbox"'
F resume vps1,vps2 >/dev/null
wait_for 30 J --arg id "$dup-h1" '.[] | select(.id == $id) | .state == "done"' && pass "and runs once resumed" || fail "renamed job"

echo "== recovery after a crash or reboot"
W1="$T/nodes/vps1"
for j in lost1 lost2; do
  mkdir -p "$W1/work/$j"
  echo "{\"prompt\": \"recovered $j\", \"max_retries\": 1}" >"$W1/jobs/running/$j.json"
  echo 999999 >"$W1/work/$j/pid"
  touch -d '-10 minutes' "$W1/jobs/running/$j.json"
done
echo '{"id":"lost1","state":"running","attempts":1}' >"$W1/work/lost1/status.json"
echo '{"id":"lost2","state":"running","attempts":2}' >"$W1/work/lost2/status.json"
FLEET_ROOT="$W1" FLEET_NODE=vps1 "$W1/app/worker/fleet-worker" recover
wait_for 20 J '.[] | select(.id == "lost1") | .state == "done" and .attempts == 2' && pass "a lost job is requeued and finishes" || fail "lost1"
check "a lost job without retries left is failed" J '.[] | select(.id == "lost2") | .state == "failed" and (.reason | test("no retries left"))'

echo "== health"
F health --changes-only >"$T/h1.txt"
check "changes-only reports new problems" grep -q "^NEW .*vps3: low disk" "$T/h1.txt"
[[ -z "$(F health --changes-only)" ]] && pass "changes-only stays quiet when nothing changed" || fail "changes-only repeated itself"
kill "${WORKER_PIDS[2]}"; wait "${WORKER_PIDS[2]}" 2>/dev/null || true
echo 1 >"$T/nodes/vps3/.heartbeat"
check "a dead worker loop is reported" bash -c "python3 '$REPO/home/bin/fleet' --config '$T/fleet.ini' health | grep -q 'vps3: the worker loop is not running'"
start_worker vps3
wait_for 10 bash -c "[[ \$(( \$(date +%s) - \$(cat '$T/nodes/vps3/.heartbeat') )) -lt 5 ]]"
F health --changes-only >"$T/h2.txt"
check "changes-only reports resolved problems" grep -q "^OK .*vps3: low disk" "$T/h2.txt"
printf 'CLAUDE_CODE_OAUTH_TOKEN=tok\n' >"$HOME/.config/fleet/providers/claude.env"
echo $(( $(date +%s) - 340 * 86400 )) >"$HOME/.config/fleet/providers/.claude.pushed"
check "health warns before a subscription token expires" bash -c \
  "python3 '$REPO/home/bin/fleet' --config '$T/fleet.ini' health | grep -q 'expires after a year'"
rm -f "$HOME/.config/fleet/providers/claude.env"
check "health reports missing credentials" bash -c \
  "python3 '$REPO/home/bin/fleet' --config '$T/fleet.ini' health | grep -q 'claude not ok (no credentials)\|claude not ok: no credentials'"
if F dispatch --prompt "nowhere to go" --channel x >/dev/null 2>"$T/err.txt"; then fail "dispatched without a healthy node"; fi
check "auto dispatch refuses when no VPS is ready" grep -q "no VPS can take a claude job" "$T/err.txt"

echo "== exec and cleanup"
[[ "$(F exec all -- echo hello | grep -c '^hello$')" == 3 ]] && pass "exec runs on every node" || fail "exec"
touch -d '-3 days' "$T/nodes/vps1/work/$id1/.pulled"
has "removed 1" F exec vps1 -- "$W1/app/worker/fleet-worker" gc --days 1 && pass "gc removes old pulled workspaces" || fail "gc"
check "gc keeps unpulled workspaces" test -d "$T/nodes/vps1/work/$slow_id"
check "fleet-worker help works" bash -c "'$W1/app/worker/fleet-worker' help | grep -q 'Commands:'"

echo "all $PASSES end-to-end checks passed"
