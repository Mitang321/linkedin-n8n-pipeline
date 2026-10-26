#!/usr/bin/env bash
# Queue a post that waits for your OK in Telegram. The row is saved as
# "pending_approval" and Telegram sends you the post with Approve and
# Reject buttons. Nothing goes out until you tap Approve. After that it
# publishes like any queued post: at the next 15-minute check after
# scheduled_at.
#
# scheduled_at must be ISO 8601 with a UTC offset, for example
# 2026-10-27T08:30:00+01:00 or 2026-10-27T07:30:00Z.
#
# Usage:
#   ./queue-with-approval.sh <scheduled_at> "Your post text" [image_url]
#   ./queue-with-approval.sh <scheduled_at> - [image_url] < post.txt
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

if [ $# -lt 2 ] || [ $# -gt 3 ]; then
  echo "Usage: $0 <scheduled_at> \"post text\" [image_url]" >&2
  exit 1
fi
scheduled_at="$1"
if ! [[ "$scheduled_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]+)?)?(Z|[+-][0-9]{2}:[0-9]{2})$ ]]; then
  echo "scheduled_at needs a date, time and offset, e.g. 2026-10-27T08:30:00+01:00" >&2
  exit 1
fi
text=$(read_text "$2")
image_url="${3:-}"

echo "Check Telegram: this post waits there for Approve or Reject." >&2
jq -n --arg text "$text" --arg at "$scheduled_at" --arg image_url "$image_url" \
  '{action: "queue", text: $text, scheduled_at: $at, approval: "telegram", confirm: "QUEUE"}
   + (if $image_url != "" then {image_url: $image_url} else {} end)' | send
