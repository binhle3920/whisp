---
name: deploy-status
description: Check the health of the Whisp production deployment — the latest GitHub Actions deploy run and the container running on the VPS. Use when a deploy may have failed or the service looks down.
---

Report the state of the production deployment. Read-only: do not redeploy, restart, or
change anything on the VPS unless the user explicitly asks.

## 1. Latest deploy run

```bash
gh run list --workflow=deploy.yml --limit 3
```

If the most recent run failed, get the reason:

```bash
gh run view <run-id> --log-failed
```

## 2. VPS container health

The VPS is reachable via the `binhle-vps` SSH alias; the app lives in `~/apps/whisp`.

```bash
ssh binhle-vps 'cd ~/apps/whisp && git rev-parse --short HEAD && docker ps --format "{{.Names}} {{.Status}}" && curl -s http://127.0.0.1:8080/healthz'
```

The API binds to loopback on the VPS, so `/healthz` must be curled from inside the host.

If the container is not `healthy`, pull logs:

```bash
ssh binhle-vps 'docker logs --tail 50 whisp-whisp-1'
```

## 3. Report

Give a short summary: last deploy result, whether the VPS commit matches `origin/main`,
container status, and the healthz response. If something is wrong, quote the specific
error line rather than the whole log.

Common causes worth checking before speculating:

- A missing untracked file (`.env`, `credentials/google_credentials.json`,
  `config/assistant.toml`) — the deploy script bails out early and says which one.
- An expired Gmail OAuth token, which surfaces as repeated poll failures in the logs.
