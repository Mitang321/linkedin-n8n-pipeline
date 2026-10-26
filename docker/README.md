# Run n8n with Docker Compose

This folder is for people who don't use Coolify. It runs three containers:

- **n8n**, the workflow engine.
- **caddy**, a reverse proxy that gets an HTTPS certificate for your domain automatically.
- **init-files**, a one-shot container that fixes the permissions on the image upload folder and then exits.

n8n itself is not exposed to the internet. Only Caddy listens on ports 80 and 443.

You need a server with Docker and the Compose plugin, and a domain you can add DNS records to.

## Quick start

1. **Point your domain at the server.** Create an A record, for example `n8n.example.com`, with your server's public IP. Open ports 80 and 443 in the server firewall and in your cloud provider's security rules.

2. **Create the `.env` file.**

   ```bash
   cd docker
   cp .env.example .env
   ```

   Set `N8N_DOMAIN` (no `https://`) and `TIMEZONE` (for example `Europe/Paris`).

3. **Start it.**

   ```bash
   docker compose up -d
   ```

   The first start takes a minute while Caddy requests the certificate. `docker compose logs -f caddy` shows progress.

4. **Open `https://your-domain`** and create the owner account.

5. **Continue with the setup script** from the repo root:

   ```bash
   python3 scripts/setup.py
   ```

   It walks you through the rest of the setup. If you'd rather have Claude do most of it, see [docs/setup-with-claude.md](../docs/setup-with-claude.md).

## Pin the n8n version

The compose file uses `n8nio/n8n:latest` so it works out of the box. For a server you rely on, pin a version instead, for example:

```yaml
image: n8nio/n8n:2.13.0
```

Check [Docker Hub](https://hub.docker.com/r/n8nio/n8n/tags) for the current tag. Use 2.13 or newer if you want Claude to build and test workflows over MCP. Older versions can still run the workflow.

## Why init-files exists

The upload action saves images to `/home/node/.n8n-files`. n8n runs as user 1000, but a new Docker volume is owned by root, so the first upload fails with `Forbidden by access permissions`. `init-files` runs `chown -R 1000:1000` on that volume before n8n starts, every time you bring the stack up.

## Using Coolify instead

Coolify has its own proxy and handles HTTPS, so you don't need Caddy.

- **Option A:** create a new resource of type **Docker Compose Empty** and paste `docker-compose.yml` without the `caddy` service (and without the `caddy-data` / `caddy-config` volumes). Set the domain on the `n8n` service in Coolify and fill in the environment variables there.
- **Option B:** use Coolify's one-click **N8N** service, then add a volume mounted at `/home/node/.n8n-files`. If uploads fail with a permissions error, run `chown -R 1000:1000` on that volume once, or add the `init-files` service.

## Updating

```bash
docker compose pull
docker compose up -d
```

If you pinned a version, change the tag first. Read the n8n release notes before jumping a major version.

## Backups

Everything worth keeping lives in two volumes:

- `n8n-data`: workflows, credentials, data tables, execution history and the encryption key.
- `n8n-files`: uploaded images.

Back up both. Without `n8n-data` you lose your credentials and data tables. The Caddy volumes only hold certificates, which Caddy will request again if they're lost.

A simple way to snapshot a volume:

```bash
docker run --rm -v docker_n8n-data:/data -v "$PWD":/backup busybox \
  tar czf /backup/n8n-data.tar.gz -C /data .
```

The volume name is prefixed with the project name (the folder name by default). `docker volume ls` shows the exact name.
