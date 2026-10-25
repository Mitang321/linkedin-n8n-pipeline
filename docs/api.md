# API reference

Everything goes through one webhook:

```
POST https://n8n.example.com/webhook/claude-linkedin-post
X-Claude-Key: <your key>
Content-Type: application/json
```

The body is a JSON object. `action` picks what happens, and every action that changes something needs a `confirm` word. If the body doesn't match any action exactly, you get a `rejected` response and nothing happens.

The webhook answers with the output of the last node that ran, as a single JSON object. A request returns once the whole path has finished, including the LinkedIn call, the log write and the Telegram message.

Contents:

- [Authentication](#authentication)
- [How a request is routed](#how-a-request-is-routed)
- [post](#post): publish now (text, image, multi-image, article)
- [queue](#queue): publish later
- [edit](#edit): change a live post's text
- [delete](#delete): delete a live post
- [list](#list): last 20 log rows
- [cancel](#cancel): remove a post from the queue
- [upload](#upload): host an image on your server
- [GET /webhook/media](#get-webhookmedia): the public image link
- [Rejected requests](#rejected-requests)
- [HTTP errors](#http-errors)
- [Calling over MCP](#calling-over-mcp)

## Authentication

The webhook node uses n8n's Header Auth. Create a "Header Auth" credential with name `X-Claude-Key` and a long random value, and pick it in the `Webhook from Claude` node. Requests without the header, or with the wrong value, get HTTP 403 `Authorization data is wrong!` and the workflow never runs.

The media link (`GET /webhook/media`) is public on purpose, so LinkedIn and Telegram can fetch images from it.

## How a request is routed

The `Route by action` Switch checks these rules in order. The first match wins. All comparisons are case-sensitive.

| Output | Matches when |
|---|---|
| `post` | `action` is `"post"` or missing, `text` is not empty, `confirm` is `"POST"`, `image_urls` (if sent) is an array of at most 20 |
| `queue` | `action` is `"queue"`, `text` is not empty, `scheduled_at` is a valid ISO 8601 date, `confirm` is `"QUEUE"`, `image_urls` (if sent) is an array of at most 20 |
| `edit` | `action` is `"edit"`, `urn` starts with `urn:li:`, `text` is not empty, `confirm` is `"EDIT"` |
| `delete` | `action` is `"delete"`, `urn` starts with `urn:li:`, `confirm` is `"DELETE"` |
| `list` | `action` is `"list"` |
| `cancel` | `action` is `"cancel"`, `row_id` is not empty, `confirm` is `"CANCEL"` |
| `upload` | `action` is `"upload"`, `filename` and `data_base64` are not empty, `confirm` is `"UPLOAD"` |
| Rejected | anything else |

Because `action` defaults to `post`, a body with just `text` and `confirm: "POST"` publishes. Keep that in mind if you write your own client.

## post

Publishes immediately.

### Fields

| Field | Required | Notes |
|---|---|---|
| `action` | no | `"post"` (the default) |
| `text` | yes | The post text. LinkedIn allows up to 3,000 characters. |
| `confirm` | yes | `"POST"` |
| `image_url` | no | One public image URL. Makes an image post. |
| `image_urls` | no | JSON array of public image URLs. 2 or more makes a multi-image post (LinkedIn accepts 2 to 20). Exactly 1 is treated like `image_url`. Must be a real array, not a string (a string is rejected). |
| `article_url` | no | Link to share as an article card. |
| `article_title` | no | Title on the article card. |
| `article_description` | no | Description on the article card. |

### Which kind of post you get

`Prepare post` decides `media_type` in this order:

1. `image_urls` has 2 or more entries: `MULTI_IMAGE`
2. `image_url` is set, or `image_urls` has exactly 1 entry: `IMAGE`
3. `article_url` is set: `ARTICLE`
4. otherwise: `NONE` (text only)

So if you send both an image and an article link, the image wins and the article fields are ignored.

Image URLs must be reachable from your n8n server. The workflow downloads each image and uploads it to LinkedIn itself; LinkedIn never sees the original link. If you don't have a public URL for an image, use [upload](#upload) first.

### Examples

Text:

```json
{
  "action": "post",
  "text": "Shipped the first version of my LinkedIn pipeline today.",
  "confirm": "POST"
}
```

Single image:

```json
{
  "action": "post",
  "text": "How the pipeline routes a request.",
  "image_url": "https://n8n.example.com/webhook/media?f=20261025-k3f9qa-diagram.png",
  "confirm": "POST"
}
```

Multi-image:

```json
{
  "action": "post",
  "text": "Three screens from the setup.",
  "image_urls": [
    "https://n8n.example.com/webhook/media?f=20261025-a1b2c3-one.png",
    "https://n8n.example.com/webhook/media?f=20261025-d4e5f6-two.png",
    "https://n8n.example.com/webhook/media?f=20261025-g7h8i9-three.png"
  ],
  "confirm": "POST"
}
```

Article:

```json
{
  "action": "post",
  "text": "Wrote up how I self-host n8n for free.",
  "article_url": "https://example.com/blog/self-hosting-n8n",
  "article_title": "Self-hosting n8n on Oracle Cloud",
  "article_description": "Coolify, a free ARM VM and a domain.",
  "confirm": "POST"
}
```

### Response

Success:

```json
{
  "status": "posted",
  "urn": "urn:li:share:7390000000000000000",
  "post_url": "https://www.linkedin.com/feed/update/urn:li:share:7390000000000000000/",
  "error": "",
  "log_row_id": 42
}
```

Failure (LinkedIn refused, token expired, image could not be downloaded, and so on):

```json
{
  "status": "failed",
  "urn": "",
  "post_url": "",
  "error": "LinkedIn 401: {\"status\":401,\"serviceErrorCode\":65601,\"code\":\"REVOKED_ACCESS_TOKEN\",\"message\":\"The token used in the request has been revoked by the user\"}",
  "log_row_id": 43
}
```

A failed post still returns HTTP 200. Check `status`. Both outcomes are logged (`log_row_id` is the row id in `linkedin_posts`) and sent to Telegram. The exact `error` text depends on which node failed: multi-image posts produce `LinkedIn <status>: <body>`, the LinkedIn node produces its own error message.

Keep the `urn`. You need it to edit or delete the post.

### When an image upload fails

For multi-image posts, every image is uploaded before the post is created. If any upload fails (for example a link the server can't reach), no post is created and you get:

```json
{
  "status": "failed",
  "urn": "",
  "post_url": "",
  "error": "Image upload failed before posting. Upload statuses: [201,500]. Check that every image link is reachable from the n8n server.",
  "log_row_id": 12
}
```

## queue

Saves the post to `linkedin_posts` with status `queued`. The 15-minute schedule publishes it once `scheduled_at` has passed.

### Fields

Same as [post](#post), plus:

| Field | Required | Notes |
|---|---|---|
| `action` | yes | `"queue"` |
| `scheduled_at` | yes | ISO 8601 with a UTC offset, for example `2026-10-27T08:30:00+01:00` or `2026-10-27T07:30:00Z` |
| `confirm` | yes | `"QUEUE"` (not `"POST"`) |

Always include the offset. Without one, the time is open to interpretation by the data table and by the Telegram formatter, and the post can go out an hour or more off.

```json
{
  "action": "queue",
  "text": "Monday morning post.",
  "image_url": "https://n8n.example.com/webhook/media?f=20261025-k3f9qa-cover.png",
  "scheduled_at": "2026-10-27T08:30:00+01:00",
  "confirm": "QUEUE"
}
```

### Response

```json
{
  "status": "queued",
  "row_id": 44,
  "scheduled_at": "2026-10-27T08:30:00+01:00"
}
```

`scheduled_at` is echoed back as you sent it. `row_id` is what you pass to [cancel](#cancel).

### When it goes out

- The schedule runs every 15 minutes and publishes at most one due post per run, oldest `scheduled_at` first. A post goes out within about 15 minutes after its time, later if several are due at once.
- A time in the past is fine; the post goes out on the next run.
- When it publishes, the same row is updated to `posted` or `failed`. A failed queued post is not retried automatically. See [data-table.md](data-table.md#retrying-a-failed-post) for how to retry it.
- To change a queued post, cancel it and queue it again, or edit the row in the n8n Data Table view.
- The workflow does not validate `scheduled_at`. If it isn't a valid date, the insert fails and the webhook returns an n8n error instead of `queued`.

## edit

Replaces the text of a live post. Likes, comments and reposts stay. Images and article cards are not touched.

| Field | Required | Notes |
|---|---|---|
| `action` | yes | `"edit"` |
| `urn` | yes | The post URN from the post response or `list`. Must start with `urn:li:`. |
| `text` | yes | The complete new text, not a diff. |
| `confirm` | yes | `"EDIT"` |

```json
{
  "action": "edit",
  "urn": "urn:li:share:7390000000000000000",
  "text": "Shipped the first version of my LinkedIn pipeline today. Repo link in the comments.",
  "confirm": "EDIT"
}
```

The workflow sends `POST /rest/posts/{urn}` with `X-RestLi-Method: PARTIAL_UPDATE` and sets `commentary`. LinkedIn treats post text as "little text", so the workflow puts a backslash before each of `\ | { } @ [ ] ( ) < > * _ ~`. That keeps parentheses and similar characters from being eaten. `#` is left alone so hashtags keep working. A side effect: `@` is escaped too, so `@Name` shows up as plain text, not a mention.

### Response

Success:

```json
{
  "status": "edited",
  "urn": "urn:li:share:7390000000000000000",
  "logged": true
}
```

`logged` is `false` when LinkedIn accepted the edit but no row in `linkedin_posts` has that URN (for example a post you made by hand). The edit still happened.

Failure:

```json
{
  "status": "failed",
  "linkedin_status": 403,
  "linkedin_body": "{\"status\":403,\"code\":\"ACCESS_DENIED\",\"message\":\"...\"}",
  "urn": "urn:li:share:7390000000000000000"
}
```

`linkedin_body` is LinkedIn's response body as a JSON string. The post was not changed.

## delete

Deletes a live post on LinkedIn and marks its row `deleted`.

| Field | Required | Notes |
|---|---|---|
| `action` | yes | `"delete"` |
| `urn` | yes | Must start with `urn:li:` |
| `confirm` | yes | `"DELETE"` |

```json
{
  "action": "delete",
  "urn": "urn:li:share:7390000000000000000",
  "confirm": "DELETE"
}
```

The workflow sends `DELETE /rest/posts/{urn}`. Only HTTP 204 counts as deleted.

### Response

Success:

```json
{
  "status": "deleted",
  "urn": "urn:li:share:7390000000000000000",
  "logged": true
}
```

Failure (same shape as edit):

```json
{
  "status": "failed",
  "linkedin_status": 404,
  "linkedin_body": "{\"status\":404,\"message\":\"...\"}",
  "urn": "urn:li:share:7390000000000000000"
}
```

On failure the post is still live and the row is unchanged.

## list

Returns the last 20 rows of `linkedin_posts`, newest first. No confirm word, and it never changes anything.

```json
{ "action": "list" }
```

### Response

```json
{
  "posts": [
    {
      "id": 44,
      "text": "Monday morning post.",
      "status": "queued",
      "scheduled_at": "2026-10-27T07:30:00.000Z",
      "media_type": "IMAGE",
      "image_url": "https://n8n.example.com/webhook/media?f=20261025-k3f9qa-cover.png",
      "image_urls": "[]",
      "article_url": "",
      "article_title": "",
      "article_description": "",
      "urn": null,
      "post_url": null,
      "posted_at": null,
      "edited_at": null,
      "error": null,
      "media_cleaned": null,
      "createdAt": "2026-10-25T14:02:11.000Z",
      "updatedAt": "2026-10-25T14:02:11.000Z"
    }
  ]
}
```

Dates come back in UTC. `image_urls` is a JSON string, not an array. Columns that were never written are `null`. See [data-table.md](data-table.md) for every column.

On an empty table the response is `{"posts":[]}`.

## cancel

Removes a post from the queue by setting its status to `cancelled`. Only rows whose status is `queued` can be cancelled. Already published posts need [delete](#delete).

| Field | Required | Notes |
|---|---|---|
| `action` | yes | `"cancel"` |
| `row_id` | yes | The `row_id` from the queue response, or `id` from `list` |
| `confirm` | yes | `"CANCEL"` |

```json
{
  "action": "cancel",
  "row_id": 44,
  "confirm": "CANCEL"
}
```

### Response

```json
{ "status": "cancelled", "row_id": "44" }
```

If no queued row has that id (wrong id, already posted, already cancelled):

```json
{ "status": "not found or not queued", "row_id": "44" }
```

`row_id` comes back as a string either way.

## upload

Saves an image on your n8n server and returns a public link you can use as `image_url` or in `image_urls`. Useful when the image only exists on your machine or in Claude's sandbox.

| Field | Required | Notes |
|---|---|---|
| `action` | yes | `"upload"` |
| `filename` | yes | Original file name, used for the extension and the saved name |
| `data_base64` | yes | File contents as base64. A `data:image/png;base64,` prefix is allowed and stripped. |
| `mime_type` | no | For example `image/png`. If missing, guessed from the extension: png, jpg, jpeg, gif, webp. Anything else becomes `application/octet-stream`. |
| `confirm` | yes | `"UPLOAD"` |

```json
{
  "action": "upload",
  "filename": "Chart Q3.png",
  "data_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
  "confirm": "UPLOAD"
}
```

The saved name is built like this:

1. lowercase the file name
2. replace anything outside `a-z 0-9 . _ -` with `-`
3. strip leading dots and dashes, keep the last 60 characters
4. prefix with today's date (`yyyyMMdd`) and 6 random characters

So `Chart Q3.png` becomes something like `20261025-k3f9qa-chart-q3.png`. The file is written to `/home/node/.n8n-files/` inside the container, which should be a mounted volume.

### Response

```json
{
  "status": "uploaded",
  "file_name": "20261025-k3f9qa-chart-q3.png",
  "url": "https://n8n.example.com/webhook/media?f=20261025-k3f9qa-chart-q3.png"
}
```

Size limit: n8n rejects request bodies over `N8N_PAYLOAD_SIZE_MAX` (16 MB by default). Base64 adds about a third, so keep images under roughly 12 MB.

Uploaded files are emptied 7 days after the post that uses them goes live or ends. Files that are never used in a logged post are not cleaned up. See [how-it-works.md](how-it-works.md#media-cleanup).

## GET /webhook/media

```
GET https://n8n.example.com/webhook/media?f=20261025-k3f9qa-chart-q3.png
```

No auth. Returns the file with `Cache-Control: public, max-age=86400`, or HTTP 404 with the body `not found` when the file doesn't exist or has been emptied by the cleanup. The `f` value is stripped down to `a-z A-Z 0-9 . _ -` and leading dots are removed, so it can't leave the media folder.

## Rejected requests

Anything that doesn't match a rule returns HTTP 200 with:

```json
{
  "status": "rejected",
  "reason": "Unknown action or missing fields/confirm. Actions: post(text,confirm=POST) | queue(text,scheduled_at,confirm=QUEUE) | edit(urn,text,confirm=EDIT) | delete(urn,confirm=DELETE) | list | cancel(row_id,confirm=CANCEL) | upload(filename,data_base64,confirm=UPLOAD). image_urls must be a list of up to 20 links; scheduled_at must be ISO 8601 with offset. Nothing was done."
}
```

Nothing is logged and no Telegram message is sent. Common causes: lowercase confirm word, the wrong confirm word for the action (`POST` on a queue request), a missing `Content-Type: application/json` header, or a URN without the `urn:li:` prefix.

Sending a request that should be rejected is a safe way to test the webhook and your key.

## HTTP errors

| Status | Body | Meaning |
|---|---|---|
| 403 | `Authorization data is wrong!` | Missing or wrong `X-Claude-Key` |
| 404 | `The requested webhook "POST claude-linkedin-post" is not registered.` | Workflow not published/active, or wrong path |
| 500 | `Error in workflow` or similar | A node failed hard, for example a missing data table ID. Check Executions in n8n. |

See [troubleshooting.md](troubleshooting.md) for fixes.

## Calling over MCP

With n8n's MCP server enabled and the workflow exposed to it, Claude can run the workflow with the `execute_workflow` tool instead of calling the webhook. Wrap the same body like this:

```json
{
  "workflowId": "<your workflow id>",
  "executionMode": "production",
  "triggerNodeName": "Webhook from Claude",
  "inputs": {
    "webhookData": {
      "method": "POST",
      "body": {
        "action": "post",
        "text": "Hello from Claude.",
        "confirm": "POST"
      }
    }
  }
}
```

On MCP runs the `X-Claude-Key` header is not checked, since access is already controlled by your MCP token. The confirm words still apply. Setup is in [claude-mcp.md](claude-mcp.md).
