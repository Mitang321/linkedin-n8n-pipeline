# Telegram

The bot does three jobs:

1. It tells you what the pipeline did: posted, queued, edited, deleted, cancelled, failed.
2. It holds queued posts until you approve them, if you ask for that.
3. It takes a few commands: save an idea, list ideas, show status, reset the login reminder.

Telegram is optional. Everything else works without it (see [Running without Telegram](#running-without-telegram)).

Contents:

- [Setup](#setup)
- [Notifications](#notifications)
- [Approving queued posts](#approving-queued-posts)
- [Commands](#commands)
- [LinkedIn login reminder](#linkedin-login-reminder)
- [Only your chat](#only-your-chat)
- [Running without Telegram](#running-without-telegram)

## Setup

1. In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot` and follow the prompts. You get a token like `123456789:AA...`.
2. Open your new bot and send it any message. Bots can't message you until you've messaged them.
3. Find your chat ID: open `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `message.chat.id`. [@userinfobot](https://t.me/userinfobot) also tells you.

`scripts/setup.py` asks for the token (`TELEGRAM_BOT_TOKEN` in `.env`) and can detect your chat ID when you message the bot. If you set things up by hand, the token goes in a **Telegram API** credential and the chat ID replaces `YOUR_TELEGRAM_CHAT_ID` in the workflow ([walkthrough, part 6](walkthrough.md#part-6-telegram-bot)).

The `Telegram in` trigger registers a webhook with Telegram when the workflow is published. That needs n8n on a public HTTPS address. A bot can only have one webhook, so don't use the same bot in another n8n workflow's Telegram trigger.

## Notifications

All messages use HTML formatting with your text escaped. Times are shown in the workflow's timezone.

### Queued and posted

When a post has images, you get the images first, then the text:

- One image: one photo message.
- Several images: one photo per image, sent silently so your phone doesn't buzz for each one. Telegram gets at most the first 10.

Then a text message with a header line, the post type, the time and the full post text in an expandable quote:

| Event | Header | Buttons |
|---|---|---|
| Queued | **Queued** · goes out Tue 27 Oct, 08:30 / Image post · queue #44 | none |
| Queued with approval | **Waiting for your approval** · goes out ... | ✅ Approve, ✖ Reject |
| Posted | **Posted on LinkedIn** / Image post · Tue 27 Oct, 08:31 · from queue #44 | Open on LinkedIn |
| Post failed | **Post FAILED** plus `Reason:` with the first 300 characters of the error | none |

Article posts also show the article link under the text.

If a photo can't be sent (Telegram couldn't fetch the image), the text message still goes out.

### Edited, deleted, cancelled

- **Post edited** shows the new text and an Open on LinkedIn button.
- **Post deleted** and **Removed from queue** show the first image with the text as a caption (cut to 700 characters), or a text message if there's no image.
- **Cancel did nothing** means the `row_id` wasn't found or wasn't `queued`.
- **Edit FAILED** and **Delete FAILED** show LinkedIn's status code and the first 300 characters of its response, with an Open on LinkedIn button.

### Daily queue summary

At 08:00 you get **LinkedIn queue · N scheduled** with each queued post's time, number, type and the first 90 characters of its text. Posts waiting for approval aren't in it. No message when the queue is empty.

## Approving queued posts

Add `"approval": "telegram"` to a `queue` request:

```json
{
  "action": "queue",
  "text": "Monday morning post.",
  "scheduled_at": "2026-10-27T08:30:00+01:00",
  "approval": "telegram",
  "confirm": "QUEUE"
}
```

Or use [`examples/queue-with-approval.sh`](../examples/queue-with-approval.sh).

What happens:

1. The row is saved with status `pending_approval` and the webhook returns `"status": "pending_approval"` with the `row_id`.
2. Telegram sends the images, then the full text with **✅ Approve** and **✖ Reject**.
3. You tap one.
   - **Approve** sets the row to `queued`. The bot replies `Approved #44 · goes out Tue 27 Oct, 08:30`, or `goes out within 15 minutes` if the time has already passed.
   - **Reject** sets the row to `cancelled`. The bot replies `Rejected #44. It won't be posted.`
4. Tapping a button on a post that was already approved or rejected does nothing except reply `#44 was already handled`.

A pending post never goes out on its own. The 15-minute check only picks up `queued` rows, so if you never tap Approve, it just waits. If you approve after its time has passed, it goes out at the next check.

The webhook `cancel` action only works on `queued` rows. To drop a post that's still waiting, tap Reject.

The buttons send `approve:<row_id>` and `reject:<row_id>` back to the `Telegram in` trigger.

## Commands

Send these to the bot. They're not case-sensitive.

| Message | Reply |
|---|---|
| `idea your thought`, `/idea your thought` or `idea: your thought` | `Saved idea #12`. The idea is stored in the `ideas` table with source `telegram`. `idea` on its own gets `Send it like: idea your thought here`. |
| `/ideas` | The last 10 open ideas, newest first, each cut to 120 characters. |
| `/status` | Queued posts, posts waiting for approval, posts published in the last 7 days, open ideas and how old the LinkedIn login is. |
| `/reconnected` | Records now as the time you connected LinkedIn and says when the next reminder is due. |
| anything else | The list of commands. |

`/status` looks like this:

```
Pipeline status

Queued: 2
Waiting for approval: 1
Posted in last 7 days: 3
Open ideas: 7
LinkedIn login: 12 days (48 left)
```

If the login line says `unknown (send /reconnected after reconnecting)`, the `pipeline_settings` table has no valid `linkedin_connected_at` row yet. Send `/reconnected`.

Claude can read and update the same ideas over the webhook with `ideas`, `idea_add` and `idea_update` ([api.md](api.md#ideas)).

## LinkedIn login reminder

LinkedIn logins (OAuth tokens) last 60 days. After that, posts fail until you reconnect.

Every morning at 09:00 the workflow reads `linkedin_connected_at` from `pipeline_settings`. From day 50 it sends:

```
LinkedIn login expires in 8 days
Connected 52 days ago. Posts fail once it lapses.

n8n → Credentials → LinkedIn account → Reconnect, then send /reconnected here.
```

After day 60 the header changes to **LinkedIn login has probably expired**. It repeats daily until you send `/reconnected`.

The workflow can't see when you click Connect in n8n, which is why `/reconnected` exists. If the settings row is missing or its value isn't a date, no reminder is sent at all, so make sure it's seeded (`scripts/setup.py` does this; by hand, see [data-table.md](data-table.md#pipeline_settings)).

## Only your chat

The `Telegram in` trigger has its **Restrict to Chat IDs** field set to your chat ID. Updates from any other chat are ignored, so someone who finds your bot can't approve posts or add ideas.

All outgoing messages go to the same chat ID. To use a group instead, add the bot to the group, use the group's ID (it starts with `-`) everywhere, and send commands in the group.

## Running without Telegram

```bash
python3 scripts/setup.py --no-telegram
```

This disables the Telegram nodes, so the workflow runs without a Telegram credential. You lose the notifications, the approval buttons, the commands and the login reminder. Posting, queueing, editing, deleting, uploads and the ideas actions all still work over the webhook.

Don't send `"approval": "telegram"` in that setup. The post would stay `pending_approval` with no way to approve it except changing the row's status to `queued` by hand in the data table.
