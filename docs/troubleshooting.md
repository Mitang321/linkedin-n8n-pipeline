# Troubleshooting

Two places to start:

- `python3 scripts/doctor.py` checks your setup and says what's wrong.
- **Executions** in n8n. Every webhook call, Telegram update and schedule run is there, and clicking a run shows which node failed and with what input.

- [setup.py stops with an error](#setuppy-stops-with-an-error)
- [LinkedIn OAuth: redirect_uri mismatch](#linkedin-oauth-redirect_uri-mismatch)
- [Webhook returns 404 "not registered"](#webhook-returns-404-not-registered)
- [Webhook returns 403 "Authorization data is wrong!"](#webhook-returns-403-authorization-data-is-wrong)
- [Every request comes back "rejected"](#every-request-comes-back-rejected)
- [Upload fails with "Forbidden by access permissions"](#upload-fails-with-forbidden-by-access-permissions)
- [Upload fails with 413 or the request hangs](#upload-fails-with-413-or-the-request-hangs)
- [Posts start failing after about two months](#posts-start-failing-after-about-two-months)
- [Multi-image, edit or delete fail with a version error](#multi-image-edit-or-delete-fail-with-a-version-error)
- [Image post fails or the image is missing](#image-post-fails-or-the-image-is-missing)
- [Telegram stays silent](#telegram-stays-silent)
- [Telegram sends text instead of the photo](#telegram-sends-text-instead-of-the-photo)
- [Telegram shows the wrong time](#telegram-shows-the-wrong-time)
- [Approve / Reject buttons do nothing](#approve--reject-buttons-do-nothing)
- [The bot doesn't answer commands](#the-bot-doesnt-answer-commands)
- [/status says the LinkedIn login is unknown](#status-says-the-linkedin-login-is-unknown)
- [No login reminder](#no-login-reminder)
- [A queued post didn't go out](#a-queued-post-didnt-go-out)
- [An approved post didn't go out](#an-approved-post-didnt-go-out)
- [Cancel says "not found or not queued"](#cancel-says-not-found-or-not-queued)
- [Media link returns 404 after a week](#media-link-returns-404-after-a-week)
- [Edit or delete fails](#edit-or-delete-fails)
- [Data table errors after import](#data-table-errors-after-import)

## setup.py stops with an error

Run `python3 scripts/doctor.py`. It checks the setup and tells you what's missing, so you can fix that and run `setup.py` again. The usual causes:

- The n8n URL or API key in `.env` is wrong, or n8n isn't reachable over HTTPS yet.
- The n8n API is turned off, or the key was created on another instance.
- n8n is older than 2.x and has no Data Tables.

If you want to see what the script does, [walkthrough.md](walkthrough.md) has every step by hand.

## LinkedIn OAuth: redirect_uri mismatch

When you connect the LinkedIn credential, LinkedIn shows "The redirect_uri does not match the registered value".

The redirect URL in your LinkedIn app must match the one n8n uses, character for character.

1. Open the LinkedIn credential in n8n and copy the **OAuth Redirect URL**. It looks like `https://n8n.example.com/rest/oauth2-credential/callback`.
2. In the LinkedIn developer portal, open your app, go to **Auth**, and add that exact URL under **Authorized redirect URLs for your app**.
3. Save and connect again.

If the URL n8n shows starts with `http://localhost:5678`, n8n doesn't know its public address. Set `N8N_HOST`, `N8N_PROTOCOL=https` and `WEBHOOK_URL=https://n8n.example.com/` on the n8n service in Coolify, redeploy, and copy the URL again. Watch for `http` vs `https` and trailing slashes.

## Webhook returns 404 "not registered"

```
{"code":404,"message":"The requested webhook \"POST claude-linkedin-post\" is not registered."}
```

- The workflow is not published (active). Production webhooks only exist while the workflow is published. Publish it in the editor.
- You're calling the wrong path. It's `/webhook/claude-linkedin-post`. `/webhook-test/...` only works while you click "Listen for test event" in the editor.
- You're sending GET instead of POST.
- You changed the path in the `Webhook from Claude` node and didn't update your client.

The same applies to `GET /webhook/media`.

## Webhook returns 403 "Authorization data is wrong!"

The `X-Claude-Key` header is missing or its value doesn't match the Header Auth credential.

- Check the header name is exactly `X-Claude-Key` in the credential.
- Check the value has no trailing space or newline. `echo -n` matters if you copy it from a shell.
- Check the `Webhook from Claude` node uses that credential and the workflow was published after you set it.

## Every request comes back "rejected"

The body didn't match any rule in `Route by action`. Check:

- The `Content-Type: application/json` header is set. Without it n8n doesn't parse the body as JSON.
- The confirm word is uppercase and matches the action: `POST`, `QUEUE`, `EDIT`, `DELETE`, `CANCEL`, `UPLOAD`, or `IDEA` for `idea_add` and `idea_update`.
- `action` is lowercase.
- `urn` starts with `urn:li:`.
- Required fields are present and not empty. `queue` needs `scheduled_at` as a valid ISO 8601 date (like `2026-10-27T08:30:00+01:00`), `upload` needs both `filename` and `data_base64`, `idea_update` needs a numeric `idea_id` and a `status` of `used`, `dropped` or `open`.
- `image_urls` is a real JSON array of at most 20, not a string.

The full rule list is in [api.md](api.md#how-a-request-is-routed).

## Upload fails with "Forbidden by access permissions"

The `Save to disk` node can't write to `/home/node/.n8n-files`. Usually the volume mounted there is owned by root, while n8n runs as the `node` user.

Fix it from the server terminal in Coolify (or SSH):

```bash
docker ps --filter name=n8n          # find the container name
docker exec -u root <container> chown -R node:node /home/node/.n8n-files
```

Then retry the upload. If you mounted the volume somewhere else, n8n 2.x will also refuse to write there unless you add the path to `N8N_RESTRICT_FILE_ACCESS_TO`. Keeping `/home/node/.n8n-files` avoids that.

## Upload fails with 413 or the request hangs

The base64 body is larger than n8n accepts. The default `N8N_PAYLOAD_SIZE_MAX` is 16 MB, and base64 adds about a third, so the image itself should stay under roughly 12 MB. Resize or recompress it, or raise `N8N_PAYLOAD_SIZE_MAX` on the n8n service. A reverse proxy in front of n8n can have its own limit too.

## Posts start failing after about two months

LinkedIn access tokens last 60 days. When the token expires:

- `post` returns `status: "failed"` with an auth error in `error`
- Telegram shows **Post FAILED** with the reason
- queued posts go out as `failed` too

Open the LinkedIn credential in n8n and click **Reconnect** (or sign in again), then send `/reconnected` to your bot so the reminder starts counting again. Retry anything that failed; see [Retrying a failed post](data-table.md#retrying-a-failed-post).

The bot warns you every morning from day 50, as long as `pipeline_settings` has a valid `linkedin_connected_at` ([No login reminder](#no-login-reminder)).

## Multi-image, edit or delete fail with a version error

The four HTTP Request nodes that call LinkedIn's REST API send a `LinkedIn-Version` header (currently `202608`). LinkedIn supports each version for about a year. After that, these calls fail with an error about the version (LinkedIn uses the code `NONEXISTENT_VERSION`).

Update the header value to a current version (format `YYYYMM`) in all four nodes:

- `LinkedIn: init image upload`
- `LinkedIn: multi-image post`
- `LinkedIn: edit post`
- `LinkedIn: delete post`

Check LinkedIn's API changelog for anything that changed between versions. Text, article and single-image posts use n8n's LinkedIn node and are not affected by this header.

## Image post fails or the image is missing

n8n downloads every image before uploading it to LinkedIn, so the link must be reachable from the n8n server, not just from your browser.

- Links behind a login, private cloud storage links and `localhost` URLs fail.
- Links that return an HTML page (a preview page instead of the raw file) produce a broken upload.
- Test from the server: `docker exec <container> wget -qO- "<image url>" | head -c 100`.

If the image is on your machine or was generated by Claude, use the `upload` action and post the URL it returns.

For multi-image posts, all images go through the same check, and LinkedIn accepts 2 to 20 images.

## Telegram stays silent

- Message your bot first. Telegram bots can't start a conversation, so send `/start` to the bot from your account.
- Check the chat ID. It's your numeric user ID (or a group ID, which starts with `-`), not the bot's username. Send a message to the bot, then open `https://api.telegram.org/bot<token>/getUpdates` and read `message.chat.id`.
- Make sure every `YOUR_TELEGRAM_CHAT_ID` placeholder was replaced. There are 27 Telegram nodes plus the `Telegram in` trigger.
- If you ran `setup.py --no-telegram`, the Telegram nodes are disabled on purpose.
- Check the Telegram credential's bot token.

Telegram nodes continue on error, so a broken Telegram setup never stops a post. Look at the Telegram node output in the execution to see the actual error.

The morning summary is silent on purpose when the queue is empty.

## Telegram sends text instead of the photo

The photo message failed and the text went out on its own. Telegram fetches the photo itself from the URL, so the image must be publicly reachable from the internet, not just from your server. Hosted media links work as long as the file hasn't been cleaned up yet.

## Telegram shows the wrong time

Message times and the schedules (every 15 minutes, 08:00, 09:00, 03:00) all follow the workflow timezone. The export is set to `Europe/Paris`. Change it in the workflow's ⋯ → Settings → Timezone, save, and publish again.

## Approve / Reject buttons do nothing

Tapping a button sends an update to the `Telegram in` trigger. If nothing comes back:

1. **The workflow isn't published.** The trigger only exists while the workflow is published. Publish it, then tap again.
2. **Telegram has no webhook for the bot.** n8n registers it when the workflow is published, and it needs a public HTTPS URL. Check with `https://api.telegram.org/bot<TOKEN>/getWebhookInfo`: `url` should point at your n8n domain. If it's empty or points elsewhere, unpublish and publish the workflow again. Make sure `WEBHOOK_URL` on the n8n service is your public `https://` address.
3. **The bot is used somewhere else.** A bot has one webhook. If another n8n workflow (or another tool) uses the same bot token with a trigger, the last one to register wins. Use a separate bot for this pipeline.
4. **Chat ID mismatch.** `Telegram in` only accepts updates from the chat ID in its **Restrict to Chat IDs** field. If you're tapping in a different chat (say, a group, while the field has your user ID), the update is dropped. Use the same ID everywhere.

Look in **Executions** for runs that start at `Telegram in`. No runs at all means points 1 to 3; runs that stop early mean something else, and the run shows where.

If the reply is `#44 was already handled`, the row isn't `pending_approval` any more: it was approved, rejected, or changed by hand.

## The bot doesn't answer commands

Same causes as [the buttons](#approve--reject-buttons-do-nothing). Also check the message: commands must start the message (`/status`, not `hey /status`). Anything the bot doesn't recognise gets the help text, so no reply at all means the update never reached n8n.

## /status says the LinkedIn login is unknown

`unknown (send /reconnected after reconnecting)` means `pipeline_settings` has no `linkedin_connected_at` row, or its value isn't a date (for example the placeholder text was left in). Send `/reconnected` to the bot. It writes the current time, and the next `/status` shows `0 days (60 left)`.

If you didn't reconnect LinkedIn just now, that date will be a bit off. You can edit `value` in the table to the real date in ISO format.

## No login reminder

The 09:00 check reads `linkedin_connected_at` from `pipeline_settings` and only messages you from day 50. It's silent if:

- the login is less than 50 days old (normal)
- the row is missing or its value isn't a date: send `/reconnected`
- the workflow isn't published, or Telegram is disabled

## A queued post didn't go out

Check in this order:

1. **The workflow is published.** Schedules only run while it's active.
2. **The row is `queued`.** Run `list`. If it's `pending_approval`, it's waiting for you to tap Approve in Telegram. If it's `failed`, read `error`.
3. **`scheduled_at` is what you meant.** It's shown in UTC in the table. If you sent a time without an offset, it may have been read as UTC instead of your local time. Always send an offset, like `+01:00`.
4. **The workflow timezone** in workflow settings matches where you are. It affects the 8:00 and 3:00 schedules.
5. **The quarter-hour checks.** The check runs at :00, :15, :30 and :45. A post set for 08:20 goes out at 08:30. Several due posts go out one per check, oldest first.
6. **Executions.** Look for runs of `Every 15 minutes`. If they're missing, the instance was down or the workflow wasn't active.

## An approved post didn't go out

Approving only changes the row from `pending_approval` to `queued`. Publishing is still done by the 15-minute check.

- **Its time hasn't come yet.** The bot's reply says when: `Approved #44 · goes out Tue 27 Oct, 08:30`. The post goes out at the first check at or after that time.
- **The time had passed when you approved.** The reply says `within 15 minutes`. It goes out at the next quarter hour.
- **Other posts were due first.** One post per check, oldest `scheduled_at` first.
- **It went out but failed.** Run `list` and read `error` on the row, or look for a **Post FAILED** message.

If none of that fits, follow [A queued post didn't go out](#a-queued-post-didnt-go-out).

## Cancel says "not found or not queued"

`cancel` only works on rows with status `queued`. Check the row with `list`:

- `pending_approval`: tap **✖ Reject** on the Telegram message instead.
- `posted`: use `delete`.
- `cancelled`, `failed` or `deleted`: nothing to cancel.

## Media link returns 404 after a week

That's the cleanup working. Seven days after a post goes live (or is deleted, cancelled or fails), the nightly run empties its hosted images and the link returns 404. The post on LinkedIn is not affected, because LinkedIn keeps its own copy.

Queued posts are never cleaned, however far out they're scheduled. Posts waiting for approval are not protected: approve or reject them within a week if they use hosted images. If you want to reuse an image, upload it again.

## Edit or delete fails

The response has `status: "failed"` with `linkedin_status` and `linkedin_body`.

- **401**: token expired. Reconnect the LinkedIn credential.
- **403**: the post isn't yours, or the app lacks the `w_member_social` permission.
- **404**: wrong URN, or the post was already deleted. Copy the URN from `list` or the post response. Both `urn:li:share:...` and `urn:li:ugcPost:...` are valid, but the type must match the post.
- **426 or a version message**: see [the version error section](#multi-image-edit-or-delete-fail-with-a-version-error).

Edits only change the text. To change images or an article card, delete the post and publish it again.

## Data table errors after import

Errors like "Could not find data table" mean one of the table placeholders (`YOUR_POSTS_TABLE_ID`, `YOUR_IDEAS_TABLE_ID`, `YOUR_SETTINGS_TABLE_ID`) wasn't replaced, or a table lives in another project. `python3 scripts/doctor.py` should point at it. To fix it by hand, copy each table's ID from its URL, then either fix the JSON and re-import, or pick the right table in each Data Table node. Table and column names must match [data-table.md](data-table.md) exactly.
