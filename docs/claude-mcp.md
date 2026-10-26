# Connect Claude over MCP

n8n has a built-in MCP server. Once it's on, Claude can see the workflow and run it for you, so you don't have to paste curl commands. You can skip this and call the webhook directly. Everything in the pipeline works either way.

This page is about using the pipeline from Claude once it's installed. To have Claude help install it, see [setup-with-claude.md](setup-with-claude.md).

You need n8n 2.13 or newer for the parts below that build and test workflows. Running this workflow over MCP works on any n8n version that has instance-level MCP.

## 1. Turn on MCP in n8n

1. In n8n, open **Settings** → **Instance-level MCP**.
2. Enable MCP access.
3. Click **Connect** and copy the **Server URL**. It ends in `/mcp-server/http`, for example:

   ```
   https://n8n.example.com/mcp-server/http
   ```

The connect screen has two tabs. Use the one that matches your Claude client.

### OAuth (Claude.ai)

1. In Claude, go to **Settings** → **Connectors** → **Add custom connector**.
2. Paste the Server URL.
3. Claude opens n8n in a new window. Approve the connection there.

### API key (other MCP clients)

The API key tab gives you a bearer token.

- It's shown once. Copy it straight away.
- Treat it like a password. Anyone with it can run your MCP-enabled workflows.
- Regenerating it revokes the old one, so any client using the old token stops working.

## 2. Make the workflow available

MCP clients only see workflows you've opted in.

1. Open the LinkedIn workflow.
2. Click the **⋯** menu → **Settings**.
3. Turn on **Available in MCP**.
4. Save.

**Checkpoint:** ask Claude "What n8n workflows can you see?" It should list the LinkedIn workflow.

## 3. How Claude runs it

Over MCP, Claude uses `execute_workflow`. It names the webhook trigger and wraps the same JSON body you'd send with curl inside `inputs.webhookData.body`:

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
        "text": "Your approved post text goes here.",
        "confirm": "POST"
      }
    }
  }
}
```

Use `"executionMode": "manual"` to run the current draft instead of the published version.

Two things to know:

- **Confirm words still apply.** Without `"confirm": "POST"` (or `QUEUE`, `EDIT`, `DELETE`, `CANCEL`, `UPLOAD`, `IDEA`), the request is rejected and nothing happens.
- **The `X-Claude-Key` header is not checked on MCP runs.** The MCP connection itself is the lock here: your OAuth approval or your bearer token. Keep that token as safe as the header key.

The full list of actions and fields is in [api.md](api.md).

### Queue with approval

Add `"approval": "telegram"` to a queue request and the post waits for you to tap **✅ Approve** in Telegram before it can go out:

```json
{
  "action": "queue",
  "text": "Your approved post text goes here.",
  "scheduled_at": "2026-10-27T08:30:00+01:00",
  "approval": "telegram",
  "confirm": "QUEUE"
}
```

The response has `"status": "pending_approval"`. This is a good default for anything Claude queues: you approve the draft in the chat, and then once more on your phone, seeing exactly what will be posted. See [telegram.md](telegram.md#approving-queued-posts).

### Ideas

Claude can read and keep your idea list, the same one you add to from Telegram with `idea ...`:

- `{"action": "ideas"}` returns up to 50 open ideas.
- `{"action": "idea_add", "text": "...", "confirm": "IDEA"}` saves one.
- `{"action": "idea_update", "idea_id": 12, "status": "used", "used_in_row": 44, "confirm": "IDEA"}` marks one used (or `dropped`, or back to `open`).

## 4. What else Claude can do with 2.13+

From n8n 2.13, the MCP server also lets Claude search, build, test and publish workflows. That's useful if you want to change this pipeline by asking for it. Review what Claude changes before you publish, the same way you'd review a pull request.

## A working agreement

This is how I use it, and I'd suggest the same:

1. **Claude drafts.** We go back and forth on the text in the chat.
2. **I approve.** Explicitly, in the conversation.
3. **Claude sends it with the confirm word.** Only after the approval, never on its own.

The confirm word is a guard against mistakes, not a replacement for your approval. Claude can type `POST` as easily as you can. What protects you is Claude asking first and you saying yes. It helps to write this down in your Claude project instructions so it holds across chats, for example:

```
When I'm writing LinkedIn posts with you:
- Draft first and show me the full text.
- Never call the LinkedIn n8n workflow until I say "approved" or "post it".
- When queueing, add "approval": "telegram" unless I say otherwise.
- Use the confirm word only for the action I approved.
- After posting, show me the post_url from the response.
```

## Example prompts

Publishing a draft you just approved:

> Approved. Post it now with the cover image I uploaded earlier.

Queueing:

> Queue this for Tuesday at 9:15 my time, with Telegram approval. Show me the row_id when it's done.

Working from ideas:

> Show me my open post ideas and pick the two with the most potential. Draft the first one.

> That draft is approved. Queue it for Thursday 8:30 with approval, then mark idea 12 as used in that row.

Saving an idea mid-conversation:

> Save this as an idea for later: how I cut my Docker image size in half.

Checking what's live and what's waiting:

> List my recent LinkedIn posts and tell me what's still queued.

Fixing a typo on a live post:

> In the post I published this morning, change "recieve" to "receive". Use edit so the likes and comments stay.

Uploading an image to use in a post:

> Upload this screenshot to my n8n server and use the link as the image for the draft.

## Troubleshooting

- **Claude can't see the workflow:** check that **Available in MCP** is on and the workflow is saved.
- **Requests come back `rejected`:** a field or confirm word is missing. The `reason` in the response lists what each action needs.
- **The connector stopped working:** if you regenerated the API key, update it in your client. For OAuth, remove and re-add the connector.

More in [troubleshooting.md](troubleshooting.md).
