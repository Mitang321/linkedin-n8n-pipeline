#!/usr/bin/env bash
# Change the status of an idea: used, dropped or open. When you mark an
# idea used, you can pass the linkedin_posts row id of the post it became.
#
# Usage:
#   ./idea-update.sh <idea_id> <used|dropped|open> [used_in_row]
#
# Examples:
#   ./idea-update.sh 7 used 44
#   ./idea-update.sh 8 dropped
#
# Needs N8N_URL and CLAUDE_KEY in the environment. See README.md.
set -euo pipefail

: "${N8N_URL:?Set N8N_URL, for example https://n8n.example.com}"
: "${CLAUDE_KEY:?Set CLAUDE_KEY to the value of your X-Claude-Key credential}"
N8N_URL="${N8N_URL%/}"

# Send a JSON body (read from stdin) to the webhook and print the response.
send() {
  local resp code out
  resp=$(curl -sS -X POST "$N8N_URL/webhook/claude-linkedin-post" \
    -H "X-Claude-Key: $CLAUDE_KEY" \
    -H "Content-Type: application/json" \
    --data-binary @- \
    -w '\n%{http_code}')
  code="${resp##*$'\n'}"
  out="${resp%$'\n'*}"
  if command -v jq >/dev/null 2>&1 && printf '%s' "$out" | jq . 2>/dev/null; then
    :
  else
    printf '%s\n' "$out"
  fi
  if [ "$code" -ge 400 ]; then
    echo "HTTP $code" >&2
    exit 1
  fi
}

command -v jq >/dev/null 2>&1 || { echo "jq is required to build the request body" >&2; exit 1; }

if [ $# -lt 2 ] || [ $# -gt 3 ] || ! [[ "$1" =~ ^[0-9]+$ ]]; then
  echo "Usage: $0 <idea_id> <used|dropped|open> [used_in_row]   (ids from ./ideas.sh)" >&2
  exit 1
fi
case "$2" in
  used|dropped|open) ;;
  *) echo "Status must be used, dropped or open" >&2; exit 1 ;;
esac
used_in_row="${3:-}"
if [ -n "$used_in_row" ] && ! [[ "$used_in_row" =~ ^[0-9]+$ ]]; then
  echo "used_in_row must be a number (the row_id or log_row_id of the post)" >&2
  exit 1
fi

jq -n --argjson id "$1" --arg status "$2" --arg row "$used_in_row" \
  '{action: "idea_update", idea_id: $id, status: $status, confirm: "IDEA"}
   + (if $row != "" then {used_in_row: ($row | tonumber)} else {} end)' | send
