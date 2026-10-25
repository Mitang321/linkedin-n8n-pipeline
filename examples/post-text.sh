#!/usr/bin/env bash
# Publish a text post on LinkedIn right now.
#
# Usage:
#   ./post-text.sh "Your post text"
#   ./post-text.sh - < post.txt
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

# Use "-" to read the text from stdin (handy for multi-line posts).
read_text() { if [ "$1" = "-" ]; then cat; else printf '%s' "$1"; fi; }

if [ $# -ne 1 ]; then
  echo "Usage: $0 \"post text\"   (or - to read stdin)" >&2
  exit 1
fi
text=$(read_text "$1")

echo "This will publish to LinkedIn now." >&2
jq -n --arg text "$text" \
  '{action: "post", text: $text, confirm: "POST"}' | send
