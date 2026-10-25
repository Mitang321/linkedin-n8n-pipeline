# Troubleshooting

Start with **Executions** in n8n. Every webhook call and schedule run is there, and clicking a run shows which node failed and with what input. Most problems below show up clearly in that view.

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
- [A queued post didn't go out](#a-queued-post-didnt-go-out)
- [Queue request returns an error instead of "queued"](#queue-request-returns-an-error-instead-of-queued)
- [Media link returns 404 after a week](#media-link-returns-404-after-a-week)
- [Edit or delete fails](#edit-or-delete-fails)
- [Data table errors after import](#data-table-errors-after-import)

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
- The confirm word is uppercase and matches the action: `POST`, `QUEUE`, `EDIT`, `DELETE`, `CANCEL`, `UPLOAD`.
- `action` is lowercase.
- `urn` starts with `urn:li:`.
- Required fields are present and not empty. `queue` needs `scheduled_at`, `upload` needs both `filename` and `data_base64`.

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

Open the LinkedIn credential in n8n and click **Reconnect** (or sign in again). Then retry anything that failed; see [Retrying a failed post](data-table.md#retrying-a-failed-post). Put a reminder in your calendar for 55 days after each reconnect.

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
- Make sure every `YOUR_TELEGRAM_CHAT_ID` placeholder was replaced. There are many Telegram nodes.
- Check the Telegram credential's bot token.

Telegram nodes continue on error, so a broken Telegram setup never stops a post. Look at the Telegram node output in the execution to see the actual error.

The morning summary is silent on purpose when the queue is empty.

## Telegram sends text instead of the photo

The photo message failed and the workflow fell back to text. Telegram fetches the photo itself from the URL, so the image must be publicly reachable from the internet, not just from your server. Hosted media links work as long as the file hasn't been cleaned up yet.

## Telegram shows the wrong time

Message times and the schedules (every 15 minutes, 08:00, 03:00) all follow the workflow timezone. The export is set to `Europe/Paris`. Change it in the workflow's ⋯ → Settings → Timezone, save, and publish again.

## A queued post didn't go out

Check in this order:

1. **The workflow is published.** Schedules only run while it's active.
2. **The row is still `queued`.** Run `list`. If it's `failed`, read `error`.
3. **`scheduled_at` is what you meant.** It's shown in UTC in the table. If you sent a time without an offset, it may have been read as UTC instead of your local time. Always send an offset, like `+01:00`.
4. **The workflow timezone** in workflow settings matches where you are. It affects the 8:00 and 3:00 schedules.
5. **Several posts were due.** Only one goes out per 15-minute run, oldest first. The rest follow 15 minutes apart.
6. **Executions.** Look for runs of `Every 15 minutes`. If they're missing, the instance was down or the workflow wasn't active.

## Queue request returns an error instead of "queued"

`scheduled_at` isn't a valid ISO 8601 date. The router only checks that it isn't empty, so a bad value gets as far as the data table insert and fails there. Use the form `2026-10-27T08:30:00+01:00`.

## Media link returns 404 after a week

That's the cleanup working. Seven days after a post goes live (or is deleted, cancelled or fails), the nightly run empties its hosted images and the link returns 404. The post on LinkedIn is not affected, because LinkedIn keeps its own copy.

Queued posts are never cleaned, however far out they're scheduled. If you want to reuse an image, upload it again.

## Edit or delete fails

The response has `status: "failed"` with `linkedin_status` and `linkedin_body`.

- **401**: token expired. Reconnect the LinkedIn credential.
- **403**: the post isn't yours, or the app lacks the `w_member_social` permission.
- **404**: wrong URN, or the post was already deleted. Copy the URN from `list` or the post response. Both `urn:li:share:...` and `urn:li:ugcPost:...` are valid, but the type must match the post.
- **426 or a version message**: see [the version error section](#multi-image-edit-or-delete-fail-with-a-version-error).

Edits only change the text. To change images or an article card, delete the post and publish it again.

## Data table errors after import

Errors like "Could not find data table" mean the `YOUR_DATA_TABLE_ID` placeholder wasn't replaced, or the table lives in another project. Copy the table ID from the table's URL, then either fix the JSON and re-import, or pick the table in each Data Table node. Column names must match [data-table.md](data-table.md) exactly.
