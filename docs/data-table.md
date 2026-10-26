# Data tables

The workflow keeps its state in three n8n Data Tables:

| Table | What it holds | Placeholder in the workflow |
|---|---|---|
| [`linkedin_posts`](#linkedin_posts) | Every post, queued item, edit, delete and cancel. The queue is the rows whose status is `queued`. | `YOUR_POSTS_TABLE_ID` |
| [`ideas`](#ideas) | Post ideas from Telegram or Claude | `YOUR_IDEAS_TABLE_ID` |
| [`pipeline_settings`](#pipeline_settings) | Key/value settings. Right now only when you last connected LinkedIn. | `YOUR_SETTINGS_TABLE_ID` |

The column lists are in [`workflow/data-tables.json`](../workflow/data-tables.json). In every table, `id`, `createdAt` and `updatedAt` are added by n8n automatically. Dates are stored and returned in UTC.

## Creating them

`scripts/setup.py` creates all three and seeds `pipeline_settings`. To do it by hand:

1. In n8n, open **Data tables** (under Overview or in your project) and create the three tables with the exact names and columns below.
2. Open each table and copy its ID from the browser URL.
3. Replace the three placeholders in `workflow/linkedin-pipeline.json` with those IDs before importing.
4. Add the seed row to `pipeline_settings` (see [below](#pipeline_settings)).

## linkedin_posts

| Column | Type | Written by | What it holds |
|---|---|---|---|
| `id` | number (built in) | n8n | Row id. This is the `row_id` / `log_row_id` in API responses. |
| `createdAt` | date (built in) | n8n | When the row was created |
| `updatedAt` | date (built in) | n8n | Last change to the row |
| `text` | string | post, queue, edit | Post text. Replaced with the new text after an edit. |
| `status` | string | every action | `queued`, `pending_approval`, `posted`, `failed`, `deleted` or `cancelled` |
| `scheduled_at` | date | queue | When a queued post should go out. Empty for instant posts. |
| `media_type` | string | post, queue | `NONE`, `ARTICLE`, `IMAGE` or `MULTI_IMAGE` |
| `image_url` | string | post, queue | The single image URL. For multi-image posts made with `post`, the first image; empty for queued multi-image posts. |
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

### Status lifecycle

```
               queue                     15-min check
  (new row) ─────────▶ queued ─────────────────────────▶ posted ──delete──▶ deleted
     │                  ▲  │                          └─▶ failed
     │                  │  └──cancel──▶ cancelled
     │       ✅ Approve │
     │ queue +          │
     │ approval ──▶ pending_approval ──✖ Reject──▶ cancelled
     │
     │ post
     └─────────────────────────────────────────────────▶ posted ──delete──▶ deleted
                                                     └─▶ failed
```

- Edits don't change `status`. They update `text` and `edited_at`.
- Only `queued` rows can be cancelled with the `cancel` action. A `pending_approval` row is dropped with the Reject button.
- Only `queued` rows are published. A `pending_approval` row waits until you approve it.
- A delete updates the row whose `urn` matches. Deleting a post that isn't in the table still works on LinkedIn; the response just says `logged: false`.

### Example rows

A published image post:

| id | text | status | media_type | image_url | image_urls | urn | posted_at | media_cleaned |
|---|---|---|---|---|---|---|---|---|
| 42 | Shipped the first version... | posted | IMAGE | https://n8n.example.com/webhook/media?f=20261025-k3f9qa-diagram.png | [] | urn:li:share:7390000000000000000 | 2026-10-25T13:58:02Z | |

A multi-image post waiting for approval:

| id | text | status | scheduled_at | media_type | image_url | image_urls |
|---|---|---|---|---|---|---|
| 44 | Three screens from the setup. | pending_approval | 2026-10-27T07:30:00Z | MULTI_IMAGE | | ["https://n8n.example.com/webhook/media?f=...one.png", "https://...two.png", "https://...three.png"] |

## ideas

| Column | Type | What it holds |
|---|---|---|
| `id` | number (built in) | The idea number (`idea_id` in the API, `#12` in Telegram) |
| `text` | string | The idea |
| `status` | string | `open`, `used` or `dropped`. New ideas are `open`. |
| `source` | string | `telegram` or `claude` (anything added through the webhook) |
| `used_in_row` | number | Optional. The `linkedin_posts` row id of the post the idea became. |

`/ideas` in Telegram shows the 10 newest open ideas, and the `ideas` action returns up to 50. Ideas are never deleted; mark them `dropped` instead.

## pipeline_settings

| Column | Type | What it holds |
|---|---|---|
| `key` | string | Setting name |
| `value` | string | Setting value |

There's one setting:

| key | value |
|---|---|
| `linkedin_connected_at` | ISO timestamp of when you last connected LinkedIn, for example `2026-10-26T10:15:00.000+01:00` |

The 09:00 login reminder and `/status` read it, and `/reconnected` in Telegram overwrites it with the current time. Seed it when you first connect LinkedIn. If the row is missing or the value isn't a date, the reminder stays silent and `/status` says `unknown`. Sending `/reconnected` once fixes both.

## Editing rows by hand

You can edit the tables in n8n's UI. A few things that are safe and useful:

**Reschedule a queued post.** Change `scheduled_at`. The next 15-minute check picks up the new time.

**Change a queued post's text.** Edit `text` while it's still `queued` or `pending_approval`. The scheduler reads the row as it is when it publishes.

**Approve without Telegram.** Change a `pending_approval` row's `status` to `queued`.

### Retrying a failed post

Failed posts are not retried automatically. To retry one:

1. Fix the cause (reconnect the LinkedIn credential, fix the image link, and so on).
2. On the failed row, set `status` to `queued`.
3. Make sure `scheduled_at` is set to a time in the past or the near future. Rows from instant posts have no `scheduled_at`, and the scheduler skips rows without one.

It goes out on the next 15-minute check and the same row is updated.

Things to avoid:

- Don't set a `posted` row back to `queued`. It will be published a second time.
- Don't put a plain array in `image_urls` from another tool. It must be a JSON string, since the workflow parses it.
- Don't clear `media_cleaned` on a cleaned row. The files are already empty.

## Growth

None of the tables are pruned. A row is a few hundred bytes, so this only matters after many thousands of posts. To trim `linkedin_posts`, delete old `posted`, `deleted` and `cancelled` rows in the UI. Keep `queued` and `pending_approval` rows.
