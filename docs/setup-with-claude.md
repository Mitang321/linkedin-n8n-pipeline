# Let Claude set it up

If Claude is connected to your n8n instance over MCP, it can do most of the setup for you: create the data tables, fill in the placeholders, attach your credentials, test the workflow and check it live.

It can't do everything. n8n's MCP server has no tool for creating credentials or for importing a raw workflow file, so you do three short things by hand first. After that, one prompt covers the rest.

If you'd rather not use Claude for this, `scripts/setup.py` does the same job from the terminal.

## What you need

- n8n **2.13 or newer**. Older versions can run workflows over MCP but can't edit or test them.
- MCP turned on: **Settings** → **Instance-level MCP** → enable, then **Connect** and copy the server URL (it ends in `/mcp-server/http`).
- That URL added to Claude as a custom connector (**Settings** → **Connectors** → **Add custom connector**). See [claude-mcp.md](claude-mcp.md) for the details.

Some organisation accounts don't allow custom connectors. If you can't add one, use `scripts/setup.py` instead.

You also need a LinkedIn developer app and a Telegram bot. The [walkthrough](walkthrough.md) covers both.

## Do these three things first

**1. Create the three credentials in n8n** (**Credentials** → **Add credential**):

| Credential | What to fill in |
|---|---|
| LinkedIn OAuth2 API | Client ID and Client Secret from your LinkedIn app, then click **Connect** and sign in |
| Header Auth | Name: `X-Claude-Key`. Value: a long random string. Keep a copy; you need it for curl calls. |
| Telegram API | The bot token from @BotFather |

**2. Import the workflow.** **Workflows** → **Import from file** → pick `workflow/linkedin-pipeline.json`. Save it. Don't edit the placeholders; Claude will.

**3. Make it visible to Claude.** Open the workflow, click **⋯** → **Settings**, turn on **Available in MCP**, save.

## Find your four values

The prompt below starts with four values only you can provide.

- **Domain**: the address of your n8n server without `https://`, for example `n8n.example.com`.
- **Time zone**: an IANA name like `Europe/Paris` or `America/New_York`. Schedules (the 15-minute queue, the 08:00 summary, the 03:00 cleanup, the 09:00 login reminder) and the times in Telegram messages follow it.
- **Telegram chat ID**: send your bot any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and look for `message.chat.id`. Or ask @userinfobot.
- **LinkedIn person ID**: in any n8n workflow, add a **LinkedIn** node, pick your LinkedIn credential, set **Post As** to **Person**, and open the **Person** dropdown. The value behind your name is the ID. Delete the node afterwards.

## The prompt

Fill in the four lines at the top and paste the whole thing into a new Claude chat with the n8n connector enabled.

```text
Set up my LinkedIn pipeline workflow in n8n. My values:

- Domain: n8n.example.com
- Time zone: Europe/Paris
- Telegram chat ID: 123456789
- LinkedIn person ID: abc123XYZ

I've already created the three credentials (LinkedIn OAuth2 API, Header Auth
named X-Claude-Key, Telegram API), imported workflow/linkedin-pipeline.json and
turned on "Available in MCP". Do the rest, in this order, and tell me what you
did after each step.

1. Find the workflow with search_workflows (it has a webhook node called
   "Webhook from Claude") and read it with get_workflow_details. Tell me its
   id, how many nodes it has, and which nodes contain YOUR_* placeholders or
   REPLACE_* credential ids.

2. Create three data tables with create_data_table. If a table with the same
   name already exists, ask me before creating another.
   - linkedin_posts: text (string), status (string), scheduled_at (date),
     media_type (string), image_url (string), image_urls (string),
     article_url (string), article_title (string), article_description
     (string), urn (string), post_url (string), posted_at (date),
     edited_at (date), error (string), media_cleaned (boolean)
   - ideas: text (string), status (string), source (string),
     used_in_row (number)
   - pipeline_settings: key (string), value (string)
   Then add one row to pipeline_settings with add_data_table_rows:
   key = linkedin_connected_at, value = the current time as ISO 8601 with
   my time zone's offset. Note the id of each table.

3. Replace the placeholders in every node with update_workflow
   (updateNodeParameters or setNodeParameter). Change only the placeholder
   text and leave the rest of each expression exactly as it is.
   - YOUR_N8N_DOMAIN -> my domain (no https://; the workflow adds it)
   - YOUR_TELEGRAM_CHAT_ID -> my chat ID (this includes the "Telegram in"
     trigger's chatIds filter)
   - YOUR_LINKEDIN_PERSON_ID -> my person ID (some nodes have it inside
     "urn:li:person:...", keep that prefix)
   - YOUR_POSTS_TABLE_ID -> the linkedin_posts table id
   - YOUR_IDEAS_TABLE_ID -> the ideas table id
   - YOUR_SETTINGS_TABLE_ID -> the pipeline_settings table id
   Afterwards, read the workflow again and confirm no YOUR_ text is left.

4. Attach my credentials. Use list_credentials to find them, then
   setNodeCredential on every node that still has a REPLACE_* id:
   - REPLACE_LINKEDIN_CREDENTIAL -> my LinkedIn OAuth2 API credential
   - REPLACE_HEADER_AUTH_CREDENTIAL -> my Header Auth credential
   - REPLACE_TELEGRAM_CREDENTIAL -> my Telegram API credential
   If there's more than one credential of a type, ask me which one.
   Confirm no REPLACE_ id is left.

5. Set the workflow time zone to mine with setWorkflowSettings.

6. Test with test_workflow, pinning the "Webhook from Claude" output as
   [{ "json": { "headers": {}, "params": {}, "query": {}, "body": { ... } } }].
   Nothing in these tests may post to LinkedIn.
   a. body {"action": "nope"} -> expect status "rejected"
   b. body {"action": "list"} -> expect a "posts" array (empty is fine)
   c. body {"action": "queue", "text": "Setup test, will be cancelled",
      "scheduled_at": "2099-01-01T09:00:00Z", "confirm": "QUEUE"}
      -> expect status "queued" and a row_id. Then cancel it with
      body {"action": "cancel", "row_id": <that id>, "confirm": "CANCEL"}.
   Tests (c) send real Telegram messages and write to the real table.
   That's fine, but tell me to expect them. Show me each result and stop if
   anything fails.

7. Ask me before publishing. Only when I say yes, run publish_workflow.

8. Do one safe live check with execute_workflow:
   {"workflowId": "<id>", "executionMode": "production",
    "triggerNodeName": "Webhook from Claude",
    "inputs": {"webhookData": {"method": "POST",
      "body": {"action": "setup-check"}}}}
   This has no confirm word, so it must come back "rejected" and do nothing.

Never send a confirm word other than for the test queue/cancel in step 6
unless I've approved that exact action in this chat.
```

## If something goes wrong

- **Claude can't find the workflow.** Check that **Available in MCP** is on and the workflow is saved. Ask "What n8n workflows can you see?"
- **Claude says it can't create data tables or edit the workflow.** Your n8n is older than 2.13. Update, or use `scripts/setup.py`.
- **A test fails at a Telegram node.** Usually the chat ID is wrong, or you haven't sent the bot a message yet.
- **Publishing fails on "Telegram in".** Telegram only accepts HTTPS webhooks on a public domain. Check that `https://your-domain` opens in a browser.

More in [troubleshooting.md](troubleshooting.md).

## Using it with Claude afterwards

Once it's published you can just ask. Some examples:

> Draft a post about what I learned moving my side projects to Oracle Cloud. Keep it under 1,200 characters. When I approve it, queue it for Wednesday 8:30 with Telegram approval.

> What's queued?

> Delete my last post.

> Show me my open ideas and turn the second one into a draft.

One rule matters more than the rest: **Claude shows you the final text and waits for your approval before it sends any confirm word** (`POST`, `QUEUE`, `EDIT`, `DELETE`, `CANCEL`, `UPLOAD`, `IDEA`). The confirm word only protects you from malformed requests. Claude can type it as easily as you can, so your "yes" in the chat is the real safeguard. Put that rule in your Claude project instructions so it carries across chats.

Queueing with `"approval": "telegram"` adds a second check: the post is saved as `pending_approval` and your bot sends it to you with **Approve** and **Reject** buttons. It only goes out if you tap Approve.

Under the hood, Claude calls `execute_workflow` with the same JSON body you'd send with curl, wrapped like this:

```json
{
  "workflowId": "<your workflow id>",
  "executionMode": "production",
  "triggerNodeName": "Webhook from Claude",
  "inputs": {
    "webhookData": {
      "method": "POST",
      "body": {
        "action": "queue",
        "text": "The approved post text.",
        "scheduled_at": "2026-10-28T08:30:00+01:00",
        "approval": "telegram",
        "confirm": "QUEUE"
      }
    }
  }
}
```

Every action and field is listed in [api.md](api.md).
