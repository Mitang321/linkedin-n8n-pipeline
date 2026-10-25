#!/usr/bin/env bash
# Delete a live LinkedIn post. This can't be undone.
#
# Usage:
#   ./delete.sh <urn>
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

if [ $# -ne 1 ]; then
  echo "Usage: $0 <urn>" >&2
  exit 1
fi
urn="$1"
case "$urn" in
  urn:li:*) ;;
  *) echo "The URN must start with urn:li: (get it from ./list.sh)" >&2; exit 1 ;;
esac

echo "This will delete $urn from LinkedIn." >&2
jq -n --arg urn "$urn" '{action: "delete", urn: $urn, confirm: "DELETE"}' | send
