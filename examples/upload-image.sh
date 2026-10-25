#!/usr/bin/env bash
# Upload a local image to your n8n server and print its public URL.
# Use that URL as image_url (or in image_urls) in a post or queue call.
#
# The full JSON response goes to stderr, the URL alone to stdout, so you can do:
#   url=$(./upload-image.sh chart.png)
#   ./post-image.sh "$url" "Here's the chart."
#
# Usage:
#   ./upload-image.sh <file> [mime_type]
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

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  echo "Usage: $0 <file> [mime_type]" >&2
  exit 1
fi
file="$1"
mime_type="${2:-}"
if [ ! -f "$file" ]; then
  echo "No such file: $file" >&2
  exit 1
fi

# Build the body through temp files: a base64 image is too big for a
# command-line argument.
tmp_b64=$(mktemp)
tmp_resp=$(mktemp)
trap 'rm -f "$tmp_b64" "$tmp_resp"' EXIT
base64 < "$file" | tr -d '\n' > "$tmp_b64"

jq -n --arg filename "$(basename "$file")" --arg mime "$mime_type" \
  --rawfile data "$tmp_b64" \
  '{action: "upload", filename: $filename, data_base64: $data, confirm: "UPLOAD"}
   + (if $mime != "" then {mime_type: $mime} else {} end)' \
  | send > "$tmp_resp" || { cat "$tmp_resp" >&2; exit 1; }

cat "$tmp_resp" >&2
url=$(jq -r '.url // empty' < "$tmp_resp")
if [ -z "$url" ]; then
  echo "Upload failed, no url in the response." >&2
  exit 1
fi
echo "$url"
