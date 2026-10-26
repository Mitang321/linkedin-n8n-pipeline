# Manual setup, step by step (the long way)

This guide takes you from no server at all to a working pipeline, doing every step by hand. It takes an afternoon, most of it waiting for things to install or for Oracle to find you a VM.

**There's a faster way.** Once n8n is running (Parts 1 to 4), `python3 scripts/setup.py` does Parts 7, 8 and 10 for you: tables, credentials, placeholders, import. See [Get started](../README.md#get-started) in the README, or [setup-with-claude.md](setup-with-claude.md) to have Claude drive it. Use this page if you'd rather see and do each step yourself, or if the script fails and you want to know what it was trying to do.

Examples use `n8n.example.com` as the n8n domain. Replace it with yours everywhere.

What you'll end up with:

- An Ubuntu ARM VM on Oracle Cloud's Always Free tier (any VPS works; skip Part 1)
- Coolify running on it, deploying n8n (or use [docker/](../docker/README.md) instead of Parts 2 to 4)
- A LinkedIn app and a Telegram bot connected to n8n
- Three data tables, and the workflow imported, tested and published

## Part 1: Oracle Cloud VM

1. Sign up for an Oracle Cloud Always Free account.
2. Create a compute instance:
   - Shape: **Ampere A1** (ARM)
   - Image: **Ubuntu**
   - Size: I use 2 OCPU / 12 GB. Always Free allows up to 4 OCPU / 24 GB in total.
   - Add your SSH public key so you can log in.
3. If you get an "out of capacity" error, that's normal in popular regions. Upgrading the account to **Pay As You Go** usually fixes it. You still pay nothing as long as you stay inside the Always Free limits.

### Open the ports

Oracle blocks traffic in two places, and you need to open both.

**The VCN security list.** In the instance's virtual cloud network, edit the security list and add ingress rules for TCP ports:

- `80` (HTTP)
- `443` (HTTPS)
- `8000` (Coolify's dashboard, only needed for first setup)

Source CIDR `0.0.0.0/0` for all three.

**The VM's own firewall.** Oracle's Ubuntu images ship with iptables rules that block most incoming ports. SSH in and allow the same ports:

```bash
ssh ubuntu@YOUR_VM_IP

sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save
```

If the rule position (`6`) doesn't fit your setup, check with `sudo iptables -L INPUT --line-numbers` and insert the rules before the final REJECT line.

**Checkpoint:** you can SSH into the VM, and you have its public IP written down.

## Part 2: Coolify and a domain

1. Install Coolify with the official install script from the [Coolify docs](https://coolify.io/docs). At the time of writing it's:

   ```bash
   curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
   ```

   Check the docs for the current command before you run it.

2. Open `http://YOUR_VM_IP:8000` and create your Coolify admin account.
3. At your DNS provider, add an **A record** for the subdomain you want n8n on (for example `n8n.example.com`) pointing at the VM's public IP.

Check that DNS has caught up:

```bash
dig +short n8n.example.com
```

**Checkpoint:** the Coolify dashboard loads, and `dig` returns your VM's IP.

## Part 3: Deploy n8n

1. In Coolify, go to **New Resource** and pick the one-click service **N8N**. Pick the plain one, which uses SQLite. It's the lightest. Skip the Postgres and worker variants on a small box.
2. Set the domain to `https://n8n.example.com`.
3. Add these environment variables:

   ```
   GENERIC_TIMEZONE=Europe/Paris
   TZ=Europe/Paris
   EXECUTIONS_DATA_PRUNE=true
   EXECUTIONS_DATA_MAX_AGE=168
   ```

   Use your own timezone. The last two make n8n delete execution logs older than 7 days (168 hours), so the disk doesn't fill up.

4. Make sure you're on n8n 2.13 or newer. Open **Edit Compose File**, set the n8n image to:

   ```
   n8nio/n8n:latest
   ```

   Save, then **Redeploy**. The workflow itself needs n8n 2.x with Data Tables. Version 2.13+ is needed for the MCP build tools in [claude-mcp.md](claude-mcp.md).

5. Open `https://n8n.example.com` and create your n8n owner account.

**Checkpoint:** n8n loads over HTTPS, and the version shown in its settings or help menu is 2.13 or newer.

## Part 4: Storage for uploaded images

The `upload` action saves images inside the container at `/home/node/.n8n-files`. That folder needs a volume so files survive redeploys, and it needs the right owner.

1. In Coolify, open the n8n service → **General** → **Edit Compose File**.
2. Under the **n8n** service's `volumes:` list (not under Task Runners), add:

   ```yaml
         - 'n8n-files:/home/node/.n8n-files'
   ```

3. Save, then **Redeploy**.
4. Fix the folder's ownership once. In Coolify, go to **Servers** → **localhost** → **Terminal** and find the container name:

   ```bash
   docker ps | grep n8n
   ```

   Then run, with your container name:

   ```bash
   docker exec -u root <n8n-container-name> chown -R node:node /home/node/.n8n-files
   ```

If you skip the ownership step, the `upload` action fails with `Forbidden by access permissions`.

**Checkpoint:** `docker exec <n8n-container-name> ls -ld /home/node/.n8n-files` shows `node node` as owner.

## Part 5: LinkedIn developer app

1. Go to [developer.linkedin.com](https://developer.linkedin.com) and click **Create app**.
2. LinkedIn asks you to link a **Company Page**. If you don't have one, create a simple page first. It only needs a name.
3. On the **Products** tab, add:
   - **Share on LinkedIn**
   - **Sign In with LinkedIn using OpenID Connect**
4. On the **Auth** tab, add this redirect URL:

   ```
   https://n8n.example.com/rest/oauth2-credential/callback
   ```

   Copy it exactly as n8n shows it in the credential screen (Part 7). If you see `The redirect_uri does not match the registered value` later, the two URLs differ somewhere, even by one character. Check the subdomain and `http` vs `https`.

5. Copy the **Client ID** and **Client Secret**.

**Checkpoint:** both products show as added on the app, and you have the Client ID and Secret.

## Part 6: Telegram bot

Telegram is optional, but without it you lose notifications, the approval buttons, the bot commands and the login reminder. To skip it, use `python3 scripts/setup.py --no-telegram`, or by hand: disable every Telegram node (including `Telegram in`) after importing in Part 10.

1. In Telegram, open **@BotFather**, send `/newbot` and follow the prompts. It gives you a bot token like `123456789:AA...`.
2. Open your new bot and send it any message. Bots can't message you until you've messaged them first.
3. Get your chat ID. Open this in a browser, with your token:

   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

   Look for `message.chat.id`:

   ```json
   {
     "ok": true,
     "result": [
       {
         "update_id": 912345678,
         "message": {
           "chat": { "id": 987654321, "type": "private" },
           "text": "hi"
         }
       }
     ]
   }
   ```

   Here the chat ID is `987654321`. You can also get it from **@userinfobot**.

**Checkpoint:** you have a bot token and your chat ID.

More on what the bot does: [telegram.md](telegram.md).

## Part 7: n8n credentials

In n8n, create three credentials.

**LinkedIn OAuth2 API**

1. Paste the Client ID and Client Secret.
2. Leave **Organization Support** off.
3. Click **Connect** and approve in the LinkedIn window.

**Header Auth**

1. Name: `X-Claude-Key`
2. Value: a long random string. Generate one with:

   ```bash
   openssl rand -hex 24
   ```

   Save this value somewhere safe. Anything calling the webhook needs it.

**Telegram API**

1. Paste the bot token.

**Checkpoint:** all three credentials are saved, and the LinkedIn one shows as connected.

LinkedIn tokens expire after 60 days. When that happens, open the LinkedIn credential and click Connect again, then send `/reconnected` to your bot. The workflow reminds you from day 50.

## Part 8: Data tables

The workflow uses three tables. The exact columns are in [`workflow/data-tables.json`](../workflow/data-tables.json). n8n adds `id`, `createdAt` and `updatedAt` itself.

1. In n8n, open **Data tables** and create these three.

   `linkedin_posts`:

   | Column | Type |
   |---|---|
   | `text` | string |
   | `status` | string |
   | `scheduled_at` | date |
   | `media_type` | string |
   | `image_url` | string |
   | `image_urls` | string |
   | `article_url` | string |
   | `article_title` | string |
   | `article_description` | string |
   | `urn` | string |
   | `post_url` | string |
   | `posted_at` | date |
   | `edited_at` | date |
   | `error` | string |
   | `media_cleaned` | boolean |

   `ideas`:

   | Column | Type |
   |---|---|
   | `text` | string |
   | `status` | string |
   | `source` | string |
   | `used_in_row` | number |

   `pipeline_settings`:

   | Column | Type |
   |---|---|
   | `key` | string |
   | `value` | string |

2. Open each table and copy its ID from the browser's address bar.
3. In `pipeline_settings`, add one row: `key` = `linkedin_connected_at`, `value` = the current time in ISO format, for example `2026-10-26T10:15:00+01:00`. This is the date the login reminder counts from. If you skip it, send `/reconnected` to the bot once the workflow is running.

More on what each column holds: [data-table.md](data-table.md).

**Checkpoint:** the three tables exist (15, 4 and 2 columns), `pipeline_settings` has its row, and you have three IDs.

## Part 9: Your LinkedIn person ID

The workflow posts as you, so it needs your LinkedIn person ID.

1. Create a temporary workflow and add any **LinkedIn** node.
2. Select your LinkedIn credential.
3. Set **Post As** to **Person**.
4. Open the **Person** dropdown. It lists you. The value behind that entry is your ID.
5. Copy it and delete the temporary workflow.

**Checkpoint:** you have a person ID.

## Part 10: Import the workflow

### Replace the placeholders

`workflow/linkedin-pipeline.json` contains six placeholders:

| Placeholder | Replace with |
|---|---|
| `YOUR_N8N_DOMAIN` | your n8n domain, without `https://` (e.g. `n8n.example.com`) |
| `YOUR_LINKEDIN_PERSON_ID` | from Part 9 |
| `YOUR_TELEGRAM_CHAT_ID` | from Part 6 |
| `YOUR_POSTS_TABLE_ID` | the `linkedin_posts` table ID from Part 8 |
| `YOUR_IDEAS_TABLE_ID` | the `ideas` table ID |
| `YOUR_SETTINGS_TABLE_ID` | the `pipeline_settings` table ID |

Work on a copy so the original stays clean. With GNU sed (Linux):

```bash
cp workflow/linkedin-pipeline.json my-pipeline.json
sed -i \
  -e 's/YOUR_N8N_DOMAIN/n8n.example.com/g' \
  -e 's/YOUR_LINKEDIN_PERSON_ID/abc123XYZ/g' \
  -e 's/YOUR_TELEGRAM_CHAT_ID/987654321/g' \
  -e 's/YOUR_POSTS_TABLE_ID/posts-table-id/g' \
  -e 's/YOUR_IDEAS_TABLE_ID/ideas-table-id/g' \
  -e 's/YOUR_SETTINGS_TABLE_ID/settings-table-id/g' \
  my-pipeline.json
```

On macOS, use `sed -i ''` instead of `sed -i`.

Check nothing was missed:

```bash
grep -c 'YOUR_' my-pipeline.json
```

This should print `0`.

### Import and wire up credentials

1. In n8n, go to **Workflows** → **Import from file** and pick `my-pipeline.json`.
2. Some nodes show credential warnings, because the export refers to credentials named `REPLACE_LINKEDIN_CREDENTIAL`, `REPLACE_HEADER_AUTH_CREDENTIAL` and `REPLACE_TELEGRAM_CREDENTIAL`. Open each one and pick yours:
   - **Webhook from Claude** → your Header Auth credential
   - **LinkedIn** nodes and the LinkedIn **HTTP Request** nodes (image upload, multi-image post, edit, delete) → your LinkedIn credential
   - **Telegram** nodes, including the `Telegram in` trigger → your Telegram credential
3. Open the workflow settings and set the **timezone** to yours. It's set to Europe/Paris in the export. This controls when the 15-minute checks, the 08:00 summary, the 09:00 login reminder and the 03:00 cleanup run, and the times shown in Telegram.
4. **Save**, then **Publish** the workflow. Publishing also registers the `Telegram in` trigger with Telegram, which is what makes the Approve / Reject buttons and the commands work.

**Checkpoint:** no node shows a credential warning, the workflow is published, and sending `/status` to your bot gets a reply.

## Part 11: Test it safely

Start with a request that should do nothing. Set your key first:

```bash
export N8N_URL="https://n8n.example.com/webhook/claude-linkedin-post"
export CLAUDE_KEY="the value from your Header Auth credential"
```

**1. A rejected request.** An empty text and a wrong confirm word:

```bash
curl -s -X POST "$N8N_URL" \
  -H "Content-Type: application/json" \
  -H "X-Claude-Key: $CLAUDE_KEY" \
  -d '{"text":"","confirm":"NO"}'
```

Expected:

```json
{
  "status": "rejected",
  "reason": "Unknown action or missing fields/confirm. Actions: post(...) | queue(...) | ... Nothing was done."
}
```

If you get a 403 or an authorization error instead, the header value doesn't match your Header Auth credential.

**2. A list call.** Read-only, no confirm word needed:

```bash
curl -s -X POST "$N8N_URL" \
  -H "Content-Type: application/json" \
  -H "X-Claude-Key: $CLAUDE_KEY" \
  -d '{"action":"list"}'
```

On a fresh table you get an empty or near-empty `posts` list back. That proves the webhook, the key and the data table are all wired up.

(The real `reason` lists every action and its fields.)

**3. When you're ready, a real post.** Queue one with approval first, so you can see Telegram, the buttons and the scheduler work before anything reaches LinkedIn:

```bash
curl -s -X POST "$N8N_URL" \
  -H "Content-Type: application/json" \
  -H "X-Claude-Key: $CLAUDE_KEY" \
  -d '{
    "action": "queue",
    "text": "Testing my posting pipeline.",
    "scheduled_at": "2026-11-02T09:30:00+01:00",
    "approval": "telegram",
    "confirm": "QUEUE"
  }'
```

Expected:

```json
{
  "status": "pending_approval",
  "row_id": 1,
  "scheduled_at": "2026-11-02T09:30:00+01:00"
}
```

Telegram sends you the post with **✅ Approve** and **✖ Reject**. Tap Reject if you only wanted to test; nothing is posted. Tap Approve and it goes out at the scheduled time (a time on the quarter hour goes out within seconds of it; other times wait for the next 15-minute check). Telegram then sends you the post with an "Open on LinkedIn" button.

To cancel a post that's already approved (status `queued`):

```bash
curl -s -X POST "$N8N_URL" \
  -H "Content-Type: application/json" \
  -H "X-Claude-Key: $CLAUDE_KEY" \
  -d '{"action":"cancel","row_id":1,"confirm":"CANCEL"}'
```

There's a ready-made script for every action in [`examples/`](../examples/), and the full request and response reference is in [api.md](api.md).

**Checkpoint:** the rejected call returns `"status": "rejected"`, the list call returns `posts`, and Telegram pings you when something real happens.

## Part 12: Connect Claude (optional)

You can call the webhook from anywhere, but the point is to let Claude do it once you've approved a draft. See [claude-mcp.md](claude-mcp.md).

## If something breaks

Run `python3 scripts/doctor.py`. It checks the setup and tells you what's missing. Common ones:

- Upload fails with `Forbidden by access permissions`: redo the `chown` in Part 4.
- `The redirect_uri does not match the registered value`: the URL in your LinkedIn app's Auth tab doesn't exactly match the one n8n shows.
- Posts start failing after about two months: the LinkedIn token expired. Reconnect the credential and send `/reconnected`.
- The Approve / Reject buttons do nothing: the workflow isn't published, or the chat ID is wrong.
- Schedules fire at the wrong hour: check the timezone in the workflow settings and the `GENERIC_TIMEZONE` / `TZ` variables.

More in [troubleshooting.md](troubleshooting.md).
