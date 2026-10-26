# How it works

The whole pipeline is one n8n workflow, `workflow/linkedin-pipeline.json`, named "LinkedIn pipeline" and made of 133 nodes. It has seven entry points:

- `Webhook from Claude`: `POST /webhook/claude-linkedin-post`, the API
- `Media link`: `GET /webhook/media`, serves hosted images
- `Telegram in`: button taps and messages from your Telegram chat
- `Every 15 minutes`, `Every morning 8:00`, `Every morning 9:00`, `Every night 3:00`: schedules

On the canvas the nodes are arranged in labelled groups. This page goes through them in the order a request flows.

```mermaid
flowchart LR
    W[Webhook from Claude] --> R{Route by action}
    R -->|post| P[Publish]
    R -->|queue| Q[Queue a post]
    R -->|edit| E[Edit a post]
    R -->|delete| D[Delete a post]
    R -->|list| L[List recent posts]
    R -->|cancel| C[Cancel a queued post]
    R -->|upload| U[Upload media]
    R -->|ideas, idea_add, idea_update| I[Ideas]
    R -->|anything else| X[Result: rejected]

    S15[Every 15 minutes] --> N[Get next due post] --> P
    P --> LOG[Log published post]

    TG[Telegram in] --> RT{Route Telegram}
    RT -->|approve / reject| AP[Approve or reject]
    RT -->|idea, /ideas| I
    RT -->|/status, /reconnected, help| ST[Status and settings]

    S8[Every morning 8:00] --> DQ[Daily queue summary]
    S9[Every morning 9:00] --> LR[LinkedIn login reminder]
    S3[Every night 3:00] --> MC[Media cleanup]
    M[Media link GET] --> SM[Serve media]

    LOG & Q & E & D & C & DQ & LR --> T((Telegram))
    LOG & Q & E & D & C & AP --> DT[(linkedin_posts)]
    I --> IT[(ideas)]
    ST & LR --> PS[(pipeline_settings)]
    U --> F[("/home/node/.n8n-files")]
    F --> SM
    MC --> F
```

## Router

`Webhook from Claude` checks the `X-Claude-Key` header (n8n Header Auth) and is set to respond with the last node's output, so the caller waits for the whole path to finish and gets its result.

`Route by action` is a Switch with ten rules and a fallback. Each rule checks `action`, the fields that action needs, and its confirm word. The rules are listed in [api.md](api.md#how-a-request-is-routed). Anything that doesn't match goes to `Result: rejected`, which returns `{status: "rejected", reason: ...}` and does nothing else.

## Publish (text / article / image / multi-image)

Used by instant posts and by the queue.

1. `Prepare post` normalises the input. It reads fields from `body` when called from the webhook, or from the table row when called by the scheduler. It sets `media_type` (`MULTI_IMAGE`, `IMAGE`, `ARTICLE` or `NONE`), keeps `image_urls` as a JSON string, and sets `row_id` only for queued rows.
2. `Media type?` sends the item down one of four branches.
3. Text: `LinkedIn: text post` (n8n LinkedIn node).
4. Article: `LinkedIn: article post` (LinkedIn node, with URL, title and description).
5. Single image: `Download image` fetches the file, then `LinkedIn: image post` uploads and posts it.
6. Multi-image, through LinkedIn's REST API:
   - `Image list` and `One item per image` split the URLs into one item each
   - `LinkedIn: init image upload` calls `POST /rest/images?action=initializeUpload` and gets an upload URL and an image URN
   - `Download image (multi)` fetches the file
   - `LinkedIn: upload image` PUTs the bytes to the upload URL
   - `Image URN` and `Collect image URNs` gather the URNs and upload statuses back into one item
   - `All images uploaded?` checks that there are at least 2 URNs and every upload returned 2xx. If not, `Image upload failed` produces a `failed` result with the upload statuses, and nothing is sent to `/rest/posts`
   - `LinkedIn: multi-image post` calls `POST /rest/posts` with `content.multiImage.images`
   - `Multi-image result` reads the new post URN from the `x-restli-id` response header
7. `Post result` merges whichever branch ran into one shape: `status` (`posted` if there is a URN, else `failed`), `urn`, `post_url`, `error`, plus the post fields for logging.

The LinkedIn and download nodes are set to continue on error, so a failure becomes a `failed` result that gets logged and reported instead of stopping the workflow.

The REST calls send `LinkedIn-Version: 202608` and `X-Restli-Protocol-Version: 2.0.0`.

## Log published post

- `From queue?` checks `row_id`. If the post came from the queue, `Log: update queued row` updates that row (`status`, `urn`, `post_url`, `posted_at`, `error`). Otherwise `Log: insert post` adds a new row.
- `Has image? (post)` and `Several images? (post)` pick how images are sent to Telegram:
  - several images: `Images to send (post)` and `One photo per image (post)` make one item per image (first 10), and `Notify: post (each photo)` sends each one silently
  - one image: `Notify: post (photo)` sends it
  - no image: straight to the text message
- `Notify: post` sends the text message: posted or failed, the post type, the full text, and an "Open on LinkedIn" button when it worked. It runs once, after the photos.
- `Result: post` returns `{status, urn, post_url, error, log_row_id}`.

## Queue a post

- `Log: add to queue` inserts a row with the post fields and `scheduled_at`. Its status is `pending_approval` if the body has `"approval": "telegram"` (any case), otherwise `queued`. It works out `media_type` the same way `Prepare post` does.
- `Has image? (queued)`, `Several images? (queued)` and the matching photo nodes send the images the same way as for a published post.
- `Notify: queued` sends the text: "Queued" or "Waiting for your approval", when it goes out, the type, the queue number and the full text. For approval posts it adds the **✅ Approve** / **✖ Reject** buttons, with callback data `approve:<row_id>` and `reject:<row_id>`.
- `Result: queued` returns `{status, row_id, scheduled_at}`, where `status` is `pending_approval` or `queued`.

Nothing is sent to LinkedIn at this point.

## Every 15 minutes

`Every 15 minutes` fires on the clock at :00, :15, :30 and :45 and triggers `Get next due post`, which reads `linkedin_posts` for rows with `status = queued` and `scheduled_at <= now`, sorted by `scheduled_at` ascending, limit 1. If it finds one, the row goes into `Prepare post` and follows the same Publish and Log path as an instant post. If nothing is due, the run ends there.

Rows with `pending_approval` are never picked up.

## Edit a post

- `LinkedIn: edit post` sends `POST /rest/posts/{urn}` with `X-RestLi-Method: PARTIAL_UPDATE` and `{patch: {$set: {commentary: ...}}}`. The text is escaped for LinkedIn's "little text" format first (see [api.md](api.md#edit)).
- `Edit result` maps the HTTP status: under 300 is `edited`, anything else `failed`, and keeps LinkedIn's status and body.
- `Edit ok?`
  - yes: `Log: save edited text` updates `text` and `edited_at` on the row with that URN, `Notify: edited`, `Result: edit`
  - no: `Notify: edit failed`, `Result: edit failed`

## Delete a post

- `LinkedIn: delete post` sends `DELETE /rest/posts/{urn}`.
- `Delete result`: 204 is `deleted`, anything else `failed`.
- `Delete ok?`
  - yes: `Log: mark deleted` sets `status: "deleted"`, then `Has image? (deleted)` picks `Notify: deleted (photo)` (first image only) or `Notify: deleted`, then `Result: delete`
  - no: `Notify: delete failed`, `Result: delete failed`

## List recent posts

`Log: recent posts` reads the last 20 rows by `id`, and `Result: list` wraps them in `{posts: [...]}`. No Telegram message.

## Cancel a queued post

`Log: cancel queued` updates the row with that `id` only if its status is `queued`, setting it to `cancelled`. If no row matched, the output is empty and `Result: cancel` returns `not found or not queued`. The Telegram message (first image only, if there is one) says which of the two happened.

## Ideas (webhook)

- `ideas`: `Ideas: open (webhook)` reads up to 50 rows with `status = open`, newest first, and `Result: ideas` returns `{ideas: [...]}`.
- `idea_add`: `Ideas: add (webhook)` inserts `{text, status: "open", source: "claude"}` and `Result: idea saved` returns `{status: "saved", idea_id}`.
- `idea_update`: `Ideas: find by id` reads the row, `Ideas: set status` updates `status` and `used_in_row` (keeping the old `used_in_row` if none was sent), and `Result: idea updated` returns `updated` or `not found`.

None of these send a Telegram message.

## Upload media

- `Prepare upload` builds a safe file name (date, 6 random characters, sanitised original name), strips any `data:...;base64,` prefix and works out the MIME type.
- `Base64 to file` turns the string into a binary file.
- `Save to disk` writes it to `/home/node/.n8n-files/<file_name>`.
- `Result: upload` returns `{status: "uploaded", file_name, url}`. The URL domain comes from the `YOUR_N8N_DOMAIN` placeholder.

n8n 2.x only lets the file nodes touch `~/.n8n-files` by default, which is why that folder is used. Mount a volume there so files survive container restarts.

## Serve media

`Media link` listens on `GET /webhook/media?f=<file>`.

- `Read media file` reads the file. The name is stripped to `a-z A-Z 0-9 . _ -` with leading dots removed, so a request can't escape the folder. A missing file goes to `Not found`.
- `File still has content?` checks the file size. A 0-byte file (one the cleanup emptied) also goes to `Not found`.
- `Send image` returns the bytes with `Cache-Control: public, max-age=86400`. `Not found` returns 404 `not found`.

## Telegram in

`Telegram in` is a Telegram trigger for `message` and `callback_query` updates, restricted to your chat ID. `Route Telegram` is a Switch (not case-sensitive) with six rules and a fallback, checked in order:

| Output | Matches |
|---|---|
| `approve` | button data starts with `approve:` |
| `reject` | button data starts with `reject:` |
| `ideas list` | message starts with `/ideas` |
| `idea` | message starts with `idea` or `/idea` as a word (so `idea …`, `/idea …`, `idea: …`) |
| `reconnected` | message starts with `/reconnected` |
| `status` | message starts with `/status` |
| Help | anything else |

### Approve queued post

`Approve: read button` takes the row id and query id from the button. `Log: approve pending` updates that row to `queued`, but only if it is still `pending_approval`. `Answer: approve` answers the button tap ("Approved" or "Already handled"), and `Was pending? (approve)` picks `Reply: approved` (`Approved #44 · goes out <time>`, or `within 15 minutes` if the time has passed) or `Reply: already handled (approve)`.

### Reject queued post

Same shape. `Log: reject pending` sets a `pending_approval` row to `cancelled`, and the bot replies `Rejected #44. It won't be posted.` or that it was already handled.

### Save an idea (Telegram)

`Idea text` strips the `idea` / `/idea` prefix and an optional `:` or dash. `Idea has text?` either saves it with `Ideas: add (Telegram)` (source `telegram`) and replies `Saved idea #12`, or replies with an example via `Reply: idea empty`.

### List ideas (Telegram)

`Ideas: latest open` reads the 10 newest open ideas, `Ideas list text` formats them (120 characters each), and `Reply: ideas list` sends them. With no open ideas it says `No open ideas yet.`

### Reconnected (Telegram)

`Settings: save reconnect time` upserts `linkedin_connected_at = now` in `pipeline_settings`. `Reply: reconnected` confirms and gives the date of the next reminder (50 days out).

### Status (Telegram)

`Status: posts` reads all `queued`, `pending_approval` and `posted` rows, and `Status: post counts` counts them (posted only in the last 7 days). `Status: open ideas` counts open ideas, `Status: LinkedIn login` reads `linkedin_connected_at`, and `Status: message` builds the reply sent by `Reply: status`.

### Help (Telegram)

`Reply: help` lists the commands.

## LinkedIn login reminder

`Every morning 9:00` reads `linkedin_connected_at` with `Settings: LinkedIn connected at`. `Login age` works out the days since then and the days left of 60. `Login expires soon?` passes from day 50, and `Notify: LinkedIn login` sends the warning with the reconnect steps. If the row is missing, the run stops quietly.

## Media cleanup

`Every night 3:00`:

1. `Get all logged posts` reads every row.
2. `Older than 7 days, has media?` keeps rows that:
   - are not `queued`
   - are not already `media_cleaned`
   - have an `image_url` or `image_urls` entry pointing at `/webhook/media?f=`
   - have `posted_at` (or, if empty, `updatedAt`) more than 7 days ago
3. `Media files of post` and `One item per file` list the hosted file names for each row.
4. `Empty content`, `Make empty file` and `Overwrite image with empty file` replace each file with a 0-byte file.
5. `Log: mark media cleaned` sets `media_cleaned: true` on the row. Only successful writes get here: if a write fails, the row stays unmarked and is retried the next night.

External image URLs are never touched. Neither are uploads that were never used in a logged post.

Only `queued` rows are protected. A `pending_approval` row that has sat untouched for more than 7 days loses its hosted images, so approve or reject pending posts within a week, or use images hosted elsewhere for posts that will wait longer.

## Daily queue summary

`Every morning 8:00` runs `Get queued posts` (all `queued` rows, soonest first), `Collect queue` and `Notify: daily queue`, which lists each post's time, queue number, type and the first 90 characters of its text. If the queue is empty, `Get queued posts` returns nothing and no message is sent. Posts waiting for approval are not included.

## Telegram messages

What each message looks like is in [telegram.md](telegram.md#notifications). In short:

- All messages use HTML parse mode, with user text escaped.
- Posted and queued: images first (one photo per image, silent when there are several, at most 10), then the full text in an expandable quote with buttons.
- Deleted and cancelled: the first image with the text as a caption (cut to about 700 characters), or a text message.
- Times are shown in the workflow's timezone (Workflow settings → Timezone).

## Design choices

**Confirm words.** The header key proves the request came from you. The confirm word proves the request meant to do this specific thing. A client (or a model) that builds the wrong action, or reuses a body, hits the fallback and nothing happens. `list` and `ideas` have no confirm word because they can't change anything.

**Approval is just a status.** A post waiting for approval is a normal row with status `pending_approval`. The queue only looks at `queued`, so approving is one field change and nothing else in the publish path had to change. Both buttons only act on rows that are still pending, so a double tap or an old message can't publish or cancel something twice.

**One post per 15 minutes.** The queue publishes at most one post per run. If several posts end up due at the same time, for example after the server was down, they go out 15 minutes apart instead of all at once.

**Telegram never blocks posting.** Every Telegram node continues on error. If Telegram is down or the chat ID is wrong, the post is still published and logged, and the caller still gets its result. The single-photo nodes use a separate error output so a failed photo falls through to the text message.

**Why /reconnected exists.** n8n doesn't expose when an OAuth credential was last connected, so the workflow keeps its own date in `pipeline_settings`. You tell it when you reconnect.

**Files are emptied, not deleted.** The Read/Write Files node can read and write but not delete, and the Execute Command node is disabled by default in n8n 2.x. Overwriting with a 0-byte file stays inside n8n's defaults, frees the space, and makes the media link return 404. The empty files are left behind; remove them by hand if you care about the file count.

**Why some calls skip the LinkedIn node.** n8n's LinkedIn node can create text, article and single-image posts, so those use it. It can't edit, delete or create multi-image posts, so those use HTTP Request nodes against LinkedIn's REST API with the same LinkedIn OAuth credential.

**Images are downloaded by n8n.** LinkedIn's API needs the image bytes, not a link. n8n downloads each image and uploads it. The image link only has to be reachable from your server, and the public media link exists mainly so Claude can hand over files it created.

**Three small tables.** Posts, queue and log share `linkedin_posts`; the queue is just rows with `status = queued`. Ideas and settings have their own tables. See [data-table.md](data-table.md).
