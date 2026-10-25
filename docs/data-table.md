# The linkedin_posts data table

Every post, queued item, edit, delete and cancel is recorded in one n8n Data Table called `linkedin_posts`. The queue is simply the rows whose status is `queued`.

The column list is in `workflow/data-table-schema.json`.

## Creating it

1. In n8n, open **Data tables** (under Overview or in your project) and create a table named `linkedin_posts`.
2. Add the columns below with the exact names and types. `id`, `createdAt` and `updatedAt` are added by n8n automatically.
3. Open the table and copy its ID from the browser URL.
4. Replace `YOUR_DATA_TABLE_ID` in `workflow/linkedin-pipeline.json` with that ID before importing. Every Data Table node in the workflow uses it.

## Columns

| Column | Type | Written by | What it holds |
|---|---|---|---|
| `id` | number (built in) | n8n | Row id. This is the `row_id` / `log_row_id` in API responses. |
| `createdAt` | date (built in) | n8n | When the row was created |
| `updatedAt` | date (built in) | n8n | Last change to the row |
| `text` | string | post, queue, edit | Post text. Replaced with the new text after an edit. |
| `status` | string | every action | `queued`, `posted`, `failed`, `deleted` or `cancelled` |
| `scheduled_at` | date | queue | When a queued post should go out. Empty for instant posts. |
| `media_type` | string | post, queue | `NONE`, `ARTICLE`, `IMAGE` or `MULTI_IMAGE` |
| `image_url` | string | post, queue | The single image URL. For multi-image posts made with `post`, the first image. |
| `image_urls` | string | post, queue | JSON array as a string, for example `["https://...","https://..."]`. `[]` when there are none. |
| `article_url` | string | post, queue | Article link |
| `article_title` | string | post, queue | Article card title |
| `article_description` | string | post, queue | Article card description |
| `urn` | string | publish | LinkedIn post URN, for example `urn:li:share:7390000000000000000`. Empty if the post failed. |
| `post_url` | string | publish | `https://www.linkedin.com/feed/update/<urn>/` |
| `posted_at` | date | publish | When it went live. Empty if it failed. |
| `edited_at` | date | edit | Last successful edit |
| `error` | string | publish | Failure message from LinkedIn or n8n. Empty on success. |
| `media_cleaned` | boolean | nightly cleanup | `true` once the hosted images for this row were emptied |

Dates are stored and returned in UTC.

## Status lifecycle

```
                 queue                   15-min run
  (new row) ─────────────▶ queued ─────────────────────▶ posted ──delete──▶ deleted
      │                      │                        └─▶ failed
      │                      └──cancel──▶ cancelled
      │
      │ post
      └───────────────────────────────────────────────▶ posted ──delete──▶ deleted
                                                     └─▶ failed
```

- Edits don't change `status`. They update `text` and `edited_at`.
- Only `queued` rows can be cancelled.
- A delete updates the row whose `urn` matches. Deleting a post that isn't in the table still works on LinkedIn; the response just says `logged: false`.

## Example rows

A published image post:

| id | text | status | media_type | image_url | image_urls | urn | posted_at | media_cleaned |
|---|---|---|---|---|---|---|---|---|
| 42 | Shipped the first version... | posted | IMAGE | https://n8n.example.com/webhook/media?f=20261025-k3f9qa-diagram.png | [] | urn:li:share:7390000000000000000 | 2026-10-25T13:58:02Z | |

A queued multi-image post:

| id | text | status | scheduled_at | media_type | image_url | image_urls |
|---|---|---|---|---|---|---|
| 44 | Three screens from the setup. | queued | 2026-10-27T07:30:00Z | MULTI_IMAGE | | ["https://n8n.example.com/webhook/media?f=...one.png", "https://...two.png", "https://...three.png"] |

## Editing rows by hand

You can edit the table in n8n's UI. A few things that are safe and useful:

**Reschedule a queued post.** Change `scheduled_at`. The next 15-minute run picks up the new time.

**Change a queued post's text.** Edit `text` while it's still `queued`. The scheduler reads the row as it is when it publishes.

### Retrying a failed post

Failed posts are not retried automatically. To retry one:

1. Fix the cause (reconnect the LinkedIn credential, fix the image link, and so on).
2. On the failed row, set `status` to `queued`.
3. Make sure `scheduled_at` is set to a time in the past or the near future. Rows from instant posts have no `scheduled_at`, and the scheduler skips rows without one.

It goes out on the next 15-minute run and the same row is updated.

Things to avoid:

- Don't set a `posted` row back to `queued`. It will be published a second time.
- Don't put a plain array in `image_urls` from another tool. It must be a JSON string, since the workflow parses it.
- Don't clear `media_cleaned` on a cleaned row. The files are already empty.

## Growth

The table is never pruned. A row is a few hundred bytes, so this only matters after many thousands of posts. If you want to trim it, delete old `posted`, `deleted` and `cancelled` rows in the UI. Keep `queued` rows.
