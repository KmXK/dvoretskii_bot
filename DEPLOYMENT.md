# VM deployment

The checkout lives at `/home/deploy/dvoretskii`. SSH access: `ssh bot`.

This VM uses `compose.yaml`, which Docker Compose selects by default. The
original `docker-compose.*.yml` files describe the old environments.

```sh
cd /home/deploy/dvoretskii
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail=100 bot
sudo docker compose restart bot
sudo docker compose down
```

The bot, local Telegram Bot API, renderer, VictoriaMetrics, FlareSolverr,
and Caddy run in Docker.
Caddy serves the built Mini App and proxies its API to the bot. Ports 80/443
are public; metrics and application ports stay on the Docker network.
The domain from `.env` must point to this VM for HTTPS certificates to work.

The bot and renderer run as UID/GID 1000, matching the `deploy` account.
Configuration is in `.env`; Google credentials are mounted from `gkeys.json`.
Neither file is included in the image or Git. Application state is in
`db.json`, `data/`, and `state/`; it survives container replacement.

The bot connects to `http://telegram-api:8081`. This service runs with
`--local`, uses `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`, and keeps its working
directory in `state/telegram-api`. Port 8081 is not published on the host.
Both services use UID/GID 1000. The bot mounts that directory read-only at
the same absolute path so Telegram's downloaded files are accessible.
The Python client sends uploads as multipart data rather than `file://`
references to temporary paths that exist only in the bot container.

When moving a bot from public Telegram Bot API to this local server for the
first time, prepare and check the local service, stop the polling bot, call
the public API's `logOut` once, then start the bot with the local endpoint.
Never print the token or run cloud `logOut` during routine local deployments.
After successful logout, cloud login is unavailable for 10 minutes.
See https://core.telegram.org/bots/api#logout.

The local API permits uploads up to 2000 MB. Application download limits
remain separate: yt-dlp currently has a 250 MiB limit. A larger source file
can still fail before a complete uploadable video is produced.

The restored VictoriaMetrics data is in `state/victoriametrics`.
The original Grafana and JWT volume backups are retained in
`state/grafana` and `state/grafana-jwt`; the current upstream app no longer
includes a Grafana service. The original compressed snapshot is in `backups/`.

Logs use Docker's rotating local driver. Yandex instance-metadata logging
from the old VM is not enabled here. Automatic uploads to the old S3 backup
destination are not enabled by this deployment.

GitHub Actions deploys successful `master` builds via `scripts/deploy-vm.sh`.
It connects as `deploy`, verifies the VM's Ed25519 host key, pulls with
`--ff-only`, builds before replacing containers, and waits for health checks.
The deployment files are tracked in Git. A manual deployment uses:

```sh
bash scripts/deploy-vm.sh
```

Repository Actions secrets:

- `REMOTE_HOST`: VM address.
- `REMOTE_USER`: `deploy`.
- `REMOTE_PATH`: `/home/deploy/dvoretskii`.
- `SSH_KEY`: a dedicated CI private key; its public key is in `authorized_keys`.
- `SSH_HOST_KEY`: the VM's `ssh-ed25519` host public key, including key type.

Before updating the code, save a database snapshot. Git pulls from
`KmXK/dvoretskii_bot`.
