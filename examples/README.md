# Example scripts

One bash script per action. They're plain `curl` calls you can read, copy, or use to test your setup without Claude. Request and response details are in [docs/api.md](../docs/api.md).

## Setup

Set two environment variables:

| Variable | Example | What it is |
|---|---|---|
| `N8N_URL` | `https://n8n.example.com` | Your n8n base URL, no path. A trailing slash is fine. |
| `CLAUDE_KEY` | `3f9c...` | The value of your `X-Claude-Key` Header Auth credential in n8n |

```bash
export N8N_URL=https://n8n.example.com
export CLAUDE_KEY='your-key-here'
```

To keep the key out of your shell history, put both lines in a file like `.env.local` (add it to `.gitignore`) and run `source .env.local`.

You also need `curl` and `jq` 1.6 or newer. `jq` builds the request bodies so quotes, newlines and emoji in your text are escaped correctly. `list.sh` works without it.

## Scripts

| Script | Action | Usage |
|---|---|---|
| `list.sh` | list | `./list.sh` |
| `post-text.sh` | post | `./post-text.sh "text"` |
| `post-image.sh` | post | `./post-image.sh <image_url> "text"` |
| `post-multi-image.sh` | post | `./post-multi-image.sh "text" <url> <url> [...]` |
| `post-article.sh` | post | `./post-article.sh <article_url> "text" ["title"] ["description"]` |
| `queue.sh` | queue | `./queue.sh <scheduled_at> "text" [image_url]` |
| `cancel.sh` | cancel | `./cancel.sh <row_id>` |
| `edit.sh` | edit | `./edit.sh <urn> "new text"` |
| `delete.sh` | delete | `./delete.sh <urn>` |
| `upload-image.sh` | upload | `./upload-image.sh <file> [mime_type]` |

Wherever a script takes post text, you can pass `-` instead and pipe the text in. That's the easy way to post multi-line text:

```bash
./post-text.sh - < post.txt
```

## Things to know

**The post scripts publish for real.** Each one sends `confirm: "POST"` and prints a one-line warning before it does. There's no dry run. If you want to test safely, start with `./list.sh`, or send a request that should be rejected:

```bash
curl -sS -X POST "$N8N_URL/webhook/claude-linkedin-post" \
  -H "X-Claude-Key: $CLAUDE_KEY" -H "Content-Type: application/json" \
  -d '{"action":"post","text":"test"}'
```

It has no confirm word, so you get `{"status":"rejected", ...}` and nothing happens.

**scheduled_at needs an offset.** Use `2026-10-27T08:30:00+01:00` or `2026-10-27T07:30:00Z`. `queue.sh` refuses times without one.

**Keep the URN.** The post scripts print a `urn`. You need it for `edit.sh` and `delete.sh`. `list.sh` shows it too.

**upload-image.sh prints only the URL on stdout.** The full response goes to stderr, so you can chain it:

```bash
url=$(./upload-image.sh chart.png)
./post-image.sh "$url" "Here's the chart from this week."
```

For a multi-image post:

```bash
a=$(./upload-image.sh one.png)
b=$(./upload-image.sh two.png)
./post-multi-image.sh "Two screens from the setup." "$a" "$b"
```

**Errors.** If the server answers with HTTP 400 or above, the script prints the body and the status and exits with 1. A `rejected` or `failed` status in the JSON comes with HTTP 200, so read the `status` field. See [docs/troubleshooting.md](../docs/troubleshooting.md).
