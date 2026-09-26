# Deploy on a VPS

Whisp is designed to run continuously on a small Linux VPS with Docker Compose. Its
SQLite database stays on the host, and Docker restarts the service after failures and
server reboots.

## Server requirements

- A Linux VPS with Docker Engine and Docker Compose
- SSH access
- Outbound HTTPS access to Gmail, OpenRouter, and Telegram
- At least 1 GB of memory and 1 GB of free disk space

No public domain or inbound web port is required. The Compose configuration binds the
operational API to `127.0.0.1` on the VPS.

## Install

Clone Whisp into a private directory on the server:

```bash
mkdir -p ~/apps
chmod 700 ~/apps
git clone https://github.com/binhle3920/whisp.git ~/apps/whisp
cd ~/apps/whisp
```

Copy these local runtime files to the same paths on the server:

- `.env`
- `credentials/google_credentials.json`
- `credentials/google_token.json`
- `config/assistant.toml`
- `data/whisp.db` if preserving an existing cursor and processed-message history

Keep the deployment directory and secret files private:

```bash
chmod 700 ~/apps/whisp ~/apps/whisp/credentials ~/apps/whisp/data
chmod 600 ~/apps/whisp/.env ~/apps/whisp/credentials/*.json
```

Build and start the service:

```bash
cd ~/apps/whisp
docker compose -f docker-compose.yml -f compose.vps.yml up --build -d
docker compose -f docker-compose.yml -f compose.vps.yml ps
docker compose -f docker-compose.yml -f compose.vps.yml logs --tail=100 whisp
```

The VPS override uses host networking for outbound DNS compatibility while still
binding Whisp itself only to `127.0.0.1`.

## Verify

On the VPS, verify the private health endpoint:

```bash
curl --fail http://127.0.0.1:8080/healthz
```

To inspect it from another computer without exposing the API publicly, open an SSH
tunnel:

```bash
ssh -L 8080:127.0.0.1:8080 your-vps
```

Then visit `http://127.0.0.1:8080/dashboard` locally for a readable overview of health,
recent email and poll activity (it asks for the dashboard login), or
`http://127.0.0.1:8080/status` for the raw JSON. The `git_commit` field shows the commit
the running container was built from; it is `unknown` for images built without the
deploy script.

### Public IP health check

To publish `/healthz` and the password-protected `/dashboard` through the VPS Nginx
server while keeping `/status` private, first set `WHISP_DASHBOARD_USERNAME` and
`WHISP_DASHBOARD_PASSWORD` in `.env` and redeploy, then run:

```bash
sudo ./deploy/install-public-health.sh
```

The public endpoints are `http://159.198.66.238/healthz` and
`http://159.198.66.238/dashboard`. Whisp remains bound to `127.0.0.1:8080`; Nginx
rate-limits dashboard requests and returns `404` for every other path.

Over plain HTTP the dashboard login travels unencrypted. Serve it over HTTPS before
relying on it from untrusted networks.

## Update

Back up the small state database and redeploy:

```bash
cd ~/apps/whisp
cp data/whisp.db "data/whisp.db.backup-$(date +%Y%m%d-%H%M%S)"
git pull --ff-only
docker compose -f docker-compose.yml -f compose.vps.yml up --build -d
docker compose -f docker-compose.yml -f compose.vps.yml ps
```

## Operations

Useful commands from `~/apps/whisp`:

```bash
docker compose -f docker-compose.yml -f compose.vps.yml logs -f --tail=100 whisp
docker compose -f docker-compose.yml -f compose.vps.yml restart whisp
docker compose -f docker-compose.yml -f compose.vps.yml stop
docker compose -f docker-compose.yml -f compose.vps.yml up -d
```

The `restart: unless-stopped` policy brings Whisp back after a crash or VPS reboot. If
you intentionally run `docker compose stop`, it remains stopped until you start it
again. Container logs are rotated to prevent them from filling the server disk.
