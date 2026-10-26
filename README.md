# linkedin-n8n-pipeline

Write LinkedIn posts with Claude, approve them, and let your own n8n server publish them through LinkedIn's official API.

![Cover](assets/cover-receipt.png)

It's one n8n workflow. Claude (or curl, or anything that can send JSON) calls a webhook, n8n posts to LinkedIn, logs the result in n8n Data Tables and tells you on Telegram. I run it on an Oracle Cloud Always Free VM, so hosting costs nothing. Each release is tested with simulated data before it goes out.

## What it does

- Publishes text, single-image, multi-image (2 to 20) and article posts
- Queues posts for a set time, checked every 15 minutes
- Can hold a queued post until you tap **✅ Approve** in Telegram
- Edits a live post's text without losing its likes and comments, and deletes posts
- Hosts images on your server and gives you a public link to use in a post
- Keeps a list of post ideas you can add to from Telegram or from Claude
- Sends a Telegram message for everything that happens, a daily queue summary, and a reminder before your LinkedIn login expires
- Cleans up hosted images a week after they're no longer needed

## Get started

Pick the path that fits.

| Path | Time | Start here |
|---|---|---|
| I already run n8n | about 10 minutes | [below](#i-already-run-n8n) |
| Starting from zero | an afternoon | [below](#starting-from-zero) |
| Let Claude set it up | depends on you | [docs/setup-with-claude.md](docs/setup-with-claude.md) |

### Three things only you can do

Whichever path you take, these need a human in a browser:

1. **Create a LinkedIn developer app** at [developer.linkedin.com](https://developer.linkedin.com). LinkedIn requires a Company Page to create one (a bare page with just a name is enough). Add the products **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect**, and add `https://n8n.example.com/rest/oauth2-credential/callback` (your domain) as a redirect URL.
2. **Click Connect** on the LinkedIn credential in n8n and approve in the LinkedIn window.
3. **Create a Telegram bot** with [@BotFather](https://t.me/BotFather) and send it one message. This is optional: run the setup with `--no-telegram` to skip Telegram entirely.

### I already run n8n

You need n8n 2.x with Data Tables (2.13+ if you want Claude to connect over MCP), reachable over HTTPS.

1. In n8n, go to **Settings → n8n API** and create an API key.
2. Copy the config file and fill in what you have: the n8n URL and API key, the LinkedIn app's Client ID and Secret, and the Telegram bot token. The comments in the file explain each value.

   ```bash
   cp .env.example .env
   ```

3. Run the setup script. It asks for anything missing, creates the three data tables and the credentials, fills in the placeholders, imports the workflow and publishes it. It's safe to run again.

   ```bash
   python3 scripts/setup.py
   ```

4. Open the LinkedIn credential in n8n and click **Connect**.
5. Find your LinkedIn person ID: open any `LinkedIn:` node in the workflow and pick yourself in the **Person** dropdown ([more detail](docs/walkthrough.md#part-9-your-linkedin-person-id)). Then:

   ```bash
   python3 scripts/setup.py person <ID>
   ```

6. Check everything:

   ```bash
   python3 scripts/doctor.py
   ```

Then try the [example scripts](examples/), starting with `./list.sh`.

### Starting from zero

1. Get a server. Oracle Cloud's Always Free ARM VM works well ([walkthrough, part 1](docs/walkthrough.md#part-1-oracle-cloud-vm)); any small VPS with Docker does too.
2. Point a domain at it and run n8n with HTTPS, either with the Docker Compose setup in [docker/](docker/README.md) or with [Coolify](docs/walkthrough.md#part-2-coolify-and-a-domain).
3. Continue with [I already run n8n](#i-already-run-n8n).

If you'd rather not use the script, [docs/walkthrough.md](docs/walkthrough.md) does every step by hand.

## Using it

Everything goes to `POST https://n8n.example.com/webhook/claude-linkedin-post` with an `X-Claude-Key` header.

| Action | Needs | Confirm word |
|---|---|---|
| `post` | `text`, optional images or article link | `POST` |
| `queue` | `text`, `scheduled_at`, optional `"approval": "telegram"` | `QUEUE` |
| `edit` | `urn`, `text` | `EDIT` |
| `delete` | `urn` | `DELETE` |
| `cancel` | `row_id` of a queued post | `CANCEL` |
| `upload` | `filename`, `data_base64` | `UPLOAD` |
| `list` | nothing | none |
| `ideas` | nothing | none |
| `idea_add` | `text` | `IDEA` |
| `idea_update` | `idea_id`, `status` (`used`, `dropped`, `open`) | `IDEA` |

In Telegram, the bot understands:

| Message | What it does |
|---|---|
| `idea your thought` | Saves an idea |
| `/ideas` | Shows the last 10 open ideas |
| `/status` | Queue, approvals, posts this week, open ideas, LinkedIn login age |
| `/reconnected` | Resets the login reminder after you reconnect LinkedIn |

More: [API reference](docs/api.md) · [Telegram](docs/telegram.md) · [example scripts](examples/) · [connect Claude over MCP](docs/claude-mcp.md)

## How it works

![How it works](assets/how-it-works.png)

The webhook checks the key and the confirm word, routes by `action`, calls LinkedIn, logs the result and tells you on Telegram. Schedules handle the queue (every 15 minutes), the morning summary (08:00), the login reminder (09:00) and image cleanup (03:00). A Telegram trigger handles the approval buttons and bot commands.

Node by node: [docs/how-it-works.md](docs/how-it-works.md).

## Safety notes

- **Two locks on every write.** Requests need the `X-Claude-Key` header, and every action that changes something needs its own confirm word. A missing or wrong word means nothing happens.
- **Official API only.** Posts go through LinkedIn's API with your own OAuth app. No scraping, no browser automation.
- **Publishing only.** The workflow doesn't send DMs, like posts or write comments.
- **Your chat only.** The Telegram trigger only accepts messages from the chat ID you configured.
- **The LinkedIn login lasts 60 days.** From day 50 the bot reminds you every morning. Reconnect the credential in n8n, then send `/reconnected`.

## Project layout

```
.
├── README.md
├── CHANGELOG.md
├── LICENSE
├── .env.example            settings for scripts/setup.py
├── assets/                 images used in the docs
├── docker/                 Docker Compose + Caddy for running n8n
├── docs/
├── examples/               curl scripts, one per action
├── scripts/
│   ├── setup.py            creates tables and credentials, imports the workflow
│   └── doctor.py           checks the setup and says what's wrong
└── workflow/
    ├── linkedin-pipeline.json
    └── data-tables.json    the three tables and their columns
```

## Docs

- [Set up with Claude](docs/setup-with-claude.md)
- [Manual setup, step by step](docs/walkthrough.md)
- [API reference](docs/api.md)
- [Telegram: notifications, approval, commands](docs/telegram.md)
- [Connect Claude over MCP](docs/claude-mcp.md)
- [How it works, node by node](docs/how-it-works.md)
- [Data tables](docs/data-table.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Changelog](CHANGELOG.md)

## License

MIT. See [LICENSE](LICENSE).

---

Built by Mitang Hindocha · [LinkedIn](https://www.linkedin.com/in/mitang-hindocha) · [mitangs.tech](https://mitangs.tech)
