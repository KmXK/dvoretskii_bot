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

The bot, renderer, VictoriaMetrics, FlareSolverr, and Caddy run in Docker.
Caddy serves the built Mini App and proxies its API to the bot. Ports 80/443
are public; metrics and application ports stay on the Docker network.
The domain from `.env` must point to this VM for HTTPS certificates to work.

The bot and renderer run as UID/GID 1000, matching the `deploy` account.
Configuration is in `.env`; Google credentials are mounted from `gkeys.json`.
Neither file is included in the image or Git. Application state is in
`db.json`, `data/`, and `state/`; it survives container replacement.

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
