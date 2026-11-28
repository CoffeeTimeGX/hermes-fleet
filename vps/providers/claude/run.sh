#!/usr/bin/env bash
# Claude provider adapter: runs ONE headless Claude Code session for a job.
#
# fleet-worker calls it as:  run.sh <job.json> <workspace-dir>
# Contract shared by every provider adapter (see vps/providers/README.md):
#   - work inside <workspace-dir>; deliverables go to <workspace-dir>/output/
#   - write <workspace-dir>/result.json and output/SUMMARY.txt
#   - exit 0 on success, non-zero on failure
#   - exit 78 when there are no credentials
#   - exit 75 when the account hit a usage limit: write logs/limit.json
#     ({"provider", "kind", "resets_at", "message"}); the worker puts the job
#     back in the queue and starts nothing until resets_at
#
# When a job comes back after a usage limit, this adapter resumes the same
# Claude session (claude --resume), so the work done before the limit is kept.
set -euo pipefail

JOB="$1"
WD="$2"
ENV_FILE="${FLEET_PROVIDER_ENV:-$HOME/.config/fleet/providers/claude.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
export PATH="$HOME/.local/bin:$PATH"
# Ride out short rate limits and capacity errors (429, 529) instead of failing.
# A usage limit that lasts longer than the wait cap ends the session; the
# worker then holds the queue until the limit resets and resumes the session.
export CLAUDE_CODE_RETRY_WATCHDOG="${CLAUDE_CODE_RETRY_WATCHDOG:-1}"
export CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS="${CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS:-900000}"

if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  echo "claude: no credentials in $ENV_FILE (on the home machine: fleet secrets push claude ${FLEET_NODE:-<node>})" >&2
  exit 78
fi
command -v claude >/dev/null 2>&1 \
  || { echo "claude: Claude Code is not installed (fleet provider install claude ${FLEET_NODE:-<node>})" >&2; exit 127; }

cd "$WD"
mkdir -p output logs

field() { jq -r --arg k "$1" '.[$k] // empty | if type == "array" then join(",") else tostring end' "$JOB"; }

prompt="$(jq -r '.prompt // empty' "$JOB")"
[[ -n "$prompt" ]] || { echo "claude: the job has no prompt" >&2; exit 65; }
channel="$(field channel)"
max_turns="$(field max_turns)"
max_turns="${max_turns:-${CLAUDE_MAX_TURNS:-}}"
model="$(field model)"
effort="$(field effort)"
budget="$(field max_budget_usd)"
allowed="$(field allowed_tools)"
mode="$(field permission_mode)"
mode="${mode:-${CLAUDE_PERMISSION_MODE:-bypassPermissions}}"

# Very long prompts go through a file: a single command-line argument is
# limited to 128 KB on Linux.
if (( ${#prompt} > 100000 )); then
  printf '%s\n' "$prompt" >JOB_PROMPT.md
  prompt="Your complete instructions are in ./JOB_PROMPT.md. Read that file first, then carry out the job exactly as it describes."
fi

# Keep the logs of earlier attempts (a retry or a resume after a usage limit).
if [[ -s logs/transcript.jsonl ]]; then
  n=1
  while [[ -e "logs/transcript.$n.jsonl" ]]; do n=$((n + 1)); done
  mv -f logs/transcript.jsonl "logs/transcript.$n.jsonl"
  if [[ -f logs/claude.stderr ]]; then mv -f logs/claude.stderr "logs/claude.$n.stderr"; fi
fi
rm -f logs/limit.json

# Resume the session that a usage limit interrupted, if Claude Code still has it.
resume_sid=""
if [[ -s .resume-session ]]; then
  sid="$(head -c 100 .resume-session | tr -cd 'A-Za-z0-9_-')"
  if [[ -n "$sid" ]] && find "$HOME/.claude/projects" -name "$sid.jsonl" -print -quit 2>/dev/null | grep -q .; then
    resume_sid="$sid"
  else
    echo "claude: the interrupted session ${sid:-?} is gone; starting the job again from the beginning"
  fi
  rm -f .resume-session
fi

system_note="You are a Claude session running unattended on fleet node ${FLEET_NODE:-unknown} \
for the channel '${channel:-unspecified}'. Job id: ${FLEET_JOB_ID:-unknown}. Work inside $WD. \
Save every final deliverable (videos, thumbnails, scripts, metadata) in ./output/. Nobody can \
answer questions during the run, so make reasonable decisions and note them. End with a short \
plain-text summary of what you produced and where; it is saved as ./output/SUMMARY.txt, so do \
not create a file with that name yourself."

# Name the fleet's skills that this VPS has (vps/skills/skills.json, `fleet skills install`).
SKILLS_LIST="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/skills/skills.json"
skills=""
if [[ -f "$SKILLS_LIST" ]]; then
  while IFS=$'\t' read -r sname sabout; do
    if [[ -f "$HOME/.claude/skills/$sname/.fleet-skill.json" ]]; then
      skills+="${skills:+; }$sname (${sabout:-see its SKILL.md})"
    fi
  done < <(jq -r '.skills[]? | [.name, (.about // "")] | @tsv' "$SKILLS_LIST" 2>/dev/null || true)
fi
if [[ -n "$skills" ]]; then
  system_note+=" Claude Code skills on this VPS, for every job: $skills. Use them when the job needs what they do, and \
write their files inside $WD."
fi

if [[ -n "$resume_sid" ]]; then
  args=(-p "Your session stopped because the Claude usage limit was reached, and it has now reset. \
Continue the same job from where you stopped: check ./output/ and the work you already did, finish \
what is missing, and end with the summary as before." --resume "$resume_sid")
else
  args=(-p "$prompt")
fi
args+=(--output-format stream-json --verbose
       --append-system-prompt "$system_note"
       --permission-mode "$mode")
[[ -n "$max_turns" ]] && args+=(--max-turns "$max_turns")
[[ -n "$model" ]] && args+=(--model "$model")
[[ -n "$effort" ]] && args+=(--effort "$effort")
[[ -n "$budget" ]] && args+=(--max-budget-usd "$budget")
[[ -n "$allowed" ]] && args+=(--allowedTools "$allowed")

auth="subscription token"
[[ -n "${ANTHROPIC_API_KEY:-}" ]] && auth="API key"
echo "claude: $(claude --version 2>/dev/null | head -n1) | $auth | mode $mode${model:+ | model $model}${effort:+ | effort $effort}${max_turns:+ | max turns $max_turns}${budget:+ | budget \$$budget}${resume_sid:+ | resuming session $resume_sid}"
code=0
claude "${args[@]}" </dev/null >logs/transcript.jsonl 2>logs/claude.stderr || code=$?

# Remember the session, so a usage limit can resume it later.
sid="$(jq -rR 'fromjson? | select(type == "object" and .type == "system" and .subtype == "init") | .session_id // empty' \
         logs/transcript.jsonl 2>/dev/null | tail -n1 || true)"
[[ -n "$sid" ]] && printf '%s\n' "$sid" >.claude-session

# The last stream-json event of type "result" carries the outcome, cost and summary.
jq -cR 'fromjson? | select(type == "object" and .type == "result")' logs/transcript.jsonl 2>/dev/null \
  | tail -n1 >result.json.tmp || true
if [[ -s result.json.tmp ]]; then
  mv -f result.json.tmp result.json
else
  rm -f result.json.tmp
  jq -n --argjson c "$code" \
    '{type:"result", is_error:true, result:"Claude Code produced no result event; see logs/claude.stderr", exit_code:$c}' >result.json
fi
jq -r '.result // ""' result.json >output/SUMMARY.txt

# Did the account hit a usage limit? Claude Code reports it as a rejected
# rate_limit_event (with the reset time), an assistant message with
# error "rate_limit", and a result with api_error "usage_limit_reached".
# Older versions printed "Claude AI usage limit reached|<epoch>", and some
# versions only write the message into the session transcript.
failed=0
if [[ "$code" -ne 0 || "$(jq -r '.is_error // false' result.json)" == "true" ]]; then failed=1; fi
if [[ $failed -eq 1 ]]; then
  limit="$(jq -nR '
    reduce (inputs | fromjson? | select(type == "object")) as $e
      ({limited: false, resets_at: null, kind: null, message: null};
       if $e.type == "rate_limit_event" then
         ($e.rate_limit_info // {}) as $i
         | if $i.status == "rejected" and (($i.isUsingOverage // false) | not)
           then .limited = true | .resets_at = ($i.resetsAt // .resets_at) | .kind = ($i.rateLimitType // .kind)
           else . end
       elif $e.type == "result" and ($e.api_error // "") == "usage_limit_reached" then
         .limited = true | .message = ($e.result // .message)
       elif $e.type == "assistant" and ($e.error // "") == "rate_limit" then
         .limited = true
       else . end)' logs/transcript.jsonl 2>/dev/null || echo '{}')"
  text="$(jq -r '.result // ""' result.json; tail -n 20 logs/claude.stderr 2>/dev/null || true)"
  if [[ -n "$sid" ]]; then
    session_file="$(find "$HOME/.claude/projects" -name "$sid.jsonl" -print -quit 2>/dev/null || true)"
    if [[ -n "$session_file" ]]; then
      text+=$'\n'"$(tail -n 30 "$session_file" | jq -rR 'fromjson? | select(type == "object" and .isApiErrorMessage == true)
                     | .message.content[]? | .text? // empty' 2>/dev/null || true)"
    fi
  fi
  if [[ "$(jq -r '.limited // false' <<<"$limit")" != "true" ]] \
     && grep -qiE "you've hit your [a-z ]*limit|usage limit reached" <<<"$text"; then
    limit="$(jq -c '.limited = true' <<<"$limit")"
  fi
  if [[ "$(jq -r '.limited // false' <<<"$limit")" == "true" ]]; then
    if [[ -z "$(jq -r '.resets_at // empty' <<<"$limit")" ]]; then
      old_epoch="$(grep -oiE 'usage limit reached[|][0-9]{9,13}' <<<"$text" | head -n1 | cut -d'|' -f2 || true)"
      [[ -n "$old_epoch" ]] && limit="$(jq -c --argjson r "$old_epoch" '.resets_at = $r' <<<"$limit")"
    fi
    msg="$(jq -r '.message // empty' <<<"$limit")"
    [[ -n "$msg" ]] || msg="$(grep -oiE "you've hit your [a-z ]*limit[^\"]*|[a-z ]*usage limit reached" <<<"$text" | head -n1 || true)"
    jq -n --argjson l "$limit" --arg m "${msg:-Claude usage limit reached}" \
      '{provider: "claude", kind: ($l.kind // "unknown"),
        resets_at: (($l.resets_at // null) | if type == "number" and . > 100000000000 then (. / 1000 | floor) else . end),
        message: $m}' >logs/limit.json
    [[ -n "$sid" ]] && printf '%s\n' "$sid" >.resume-session
    echo "claude: usage limit reached ($(jq -r '.message' logs/limit.json)); the job goes back in the queue" >&2
    exit 75
  fi
fi

if [[ "$code" -ne 0 ]]; then
  echo "claude: Claude Code exited with code $code" >&2
  tail -n 20 logs/claude.stderr >&2 || true
  exit "$code"
fi
if [[ "$(jq -r '.is_error // false' result.json)" == "true" ]]; then
  echo "claude: the session ended with an error: $(jq -r '.subtype // .result // "unknown"' result.json | head -c 300)" >&2
  exit 1
fi
echo "claude: finished in $(jq -r '((.duration_ms // 0) / 1000) | floor' result.json)s," \
     "$(jq -r '.num_turns // "?"' result.json) turns, about \$$(jq -r '.total_cost_usd // 0 | . * 100 | round / 100' result.json) of usage"
