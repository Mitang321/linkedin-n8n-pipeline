#!/usr/bin/env bash
# Publish a multi-image post (2 to 20 images) on LinkedIn right now.
# Every image URL must be reachable from your n8n server.
#
# Usage:
#   ./post-multi-image.sh "Your post text" <image_url> <image_url> [more urls...]
#   ./post-multi-image.sh - <image_url> <image_url> < post.txt
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

if [ $# -lt 3 ]; then
  echo "Usage: $0 \"post text\" <image_url> <image_url> [more urls...]" >&2
  exit 1
fi
text=$(read_text "$1")
shift
if [ $# -gt 20 ]; then
  echo "LinkedIn accepts at most 20 images, got $#." >&2
  exit 1
fi

echo "This will publish to LinkedIn now." >&2
jq -n --arg text "$text" \
  '{action: "post", text: $text, image_urls: $ARGS.positional, confirm: "POST"}' \
  --args "$@" | send
