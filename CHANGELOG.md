# Changelog

All notable changes to this project are listed here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-10-26

### Added

- Telegram approval for queued posts. Queue with `"approval": "telegram"` and the post is saved as `pending_approval`. The bot sends it to you with Approve and Reject buttons, and it only goes out once approved.
- Telegram commands: `idea …` to save an idea, `/ideas`, `/status`, `/reconnected` and `help`.
- Ideas inbox in a new `ideas` data table. New webhook actions `ideas`, `idea_add` and `idea_update` (the last two need `"confirm": "IDEA"`).
- LinkedIn login reminder. LinkedIn tokens expire after about 60 days, so from day 50 the bot reminds you daily at 09:00 to reconnect. The connection date is kept in a new `pipeline_settings` data table.
- Telegram notifications for image posts now send every image, then the full post text.
- Guided setup script (`scripts/setup.py`) and a checker (`scripts/doctor.py`).
- Docker Compose setup in `docker/` with automatic HTTPS through Caddy and a fix for upload folder permissions.
- "Let Claude set it up" guide ([docs/setup-with-claude.md](docs/setup-with-claude.md)).

### Changed

- README reorganised around three setup paths: setup script, Claude over MCP, and manual.

### Fixed

- Queued multi-image posts showed the wrong label.
- `list` on an empty table returned nothing instead of `{"posts":[]}`.
- Multi-image posts now check that every image uploaded before creating the post.
- Media cleanup retries rows it failed to update.
- Times in Telegram messages follow the workflow time zone.
- Invalid `scheduled_at` values and `image_urls` that aren't a list of at most 20 are rejected instead of failing partway.

## [1.0.0] - 2026-10-25

First release.

### Added

- Webhook actions `post`, `queue`, `edit`, `delete`, `list`, `cancel` and `upload`, each changing action guarded by a confirm word.
- Text, article, single-image and multi-image posts through the official LinkedIn API.
- Queue that publishes due posts every 15 minutes, on the quarter hour.
- Daily queue summary at 08:00 and media cleanup at 03:00.
- Log of every post in an n8n data table.
- Telegram notifications for every action.
- Walkthrough and API reference.

[1.1.0]: https://github.com/Mitang321/linkedin-n8n-pipeline/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Mitang321/linkedin-n8n-pipeline/releases/tag/v1.0.0
