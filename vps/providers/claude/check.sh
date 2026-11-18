#!/usr/bin/env bash
# Health check for the Claude provider on this node.
#   check.sh            one human-readable line
#   check.sh --json     one JSON object (fleet-worker status uses it)
#   check.sh --smoke    also run a one-turn session to prove the credentials work
set -uo pipefail

ENV_DIR="$HOME/.config/fleet/providers"
ENV_FILE="${FLEET_PROVIDER_ENV:-$ENV_DIR/claude.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
export PATH="$HOME/.local/bin:$PATH"

json=0
smoke=0
for a in "$@"; do
  case "$a" in
    --json) json=1 ;;
    --smoke) smoke=1 ;;
  esac
done

installed=false ok=true err="" version="" auth="none" smoke_result="skipped" age=""
if command -v claude >/dev/null 2>&1; then
  installed=true
  version="$(claude --version 2>/dev/null | head -n1)"
else
  ok=false
  err="Claude Code not installed"
fi
# Claude Code prefers an API key when both are set.
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  auth="api-key"
elif [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  auth="oauth-token"
else
  ok=false
  err="${err:+$err; }no credentials"
fi
pushed="$(head -c 20 "$ENV_DIR/.claude.pushed" 2>/dev/null || true)"
if [[ "$pushed" =~ ^[0-9]+$ ]]; then
  age=$(( ($(date +%s) - pushed) / 86400 ))
fi

if [[ $smoke -eq 1 && "$ok" == true ]]; then
  tmp="$(mktemp -d)"
  out="$(cd "$tmp" && timeout 180 claude -p "Reply with exactly the word OK and nothing else." \
           --max-turns 1 --output-format json </dev/null 2>&1)"
  rm -rf "$tmp"
  if jq -e '.result | test("OK")' <<<"$out" >/dev/null 2>&1; then
    smoke_result="ok"
  else
    ok=false
    smoke_result="failed"
    err="${err:+$err; }smoke test failed: $(head -c 300 <<<"$out" | tr '\n' ' ')"
  fi
fi

if [[ $json -eq 1 ]]; then
  jq -nc --arg v "$version" --arg a "$auth" --arg e "$err" --arg s "$smoke_result" --arg age "$age" \
         --argjson ok "$ok" --argjson inst "$installed" \
    '{provider:"claude", installed:$inst, ok:$ok, version:(if $v == "" then null else $v end), auth:$a,
      credential_age_days:(if $age == "" then null else ($age|tonumber) end), smoke:$s,
      error:(if $e == "" then null else $e end)}'
else
  echo "claude: ${version:-not installed} | auth: $auth${age:+ (pushed $age days ago)} | smoke: $smoke_result | $([[ $ok == true ]] && echo OK || echo "PROBLEM: $err")"
fi
[[ "$ok" == true ]]
