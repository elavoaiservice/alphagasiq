# AlphaGasIQ — Mac Mini Prototype Deployment

**Status:** Plan / prototype. Not customer-production.
**Goal:** Run AlphaGasIQ on a home Mac Mini, reachable at `https://alphagasiq.elavoai.com`,
fully isolated from the ElavoAI production server. Paper-only, validation phase.

## Why this setup
- **Isolation:** physically separate from the ElavoAI prod box → zero blast-radius to the
  revenue app / customer data.
- **Collapsed infra:** the stack is designed to shrink. For the prototype we drop Kafka
  (Redpanda) and Neo4j and run on mock data — leaving just **Postgres + Redis + api + worker + web**.
- **Secure exposure:** a **Cloudflare Tunnel** (outbound-only) publishes the subdomain with
  **no open ports** on your home router and no exposed home IP. TLS handled by Cloudflare.

⚠️ **Prototype only.** A home Mac Mini is fine for internal validation of a paper-only system.
It is **not** production-grade (residential power/internet, single box). When this becomes a
customer-facing product, migrate the same container stack to a cloud VM.

---

## 0. Prerequisites
- Mac Mini (Apple Silicon or Intel), macOS, ~16 GB RAM is plenty.
- Cloudflare account managing `elavoai.com` DNS (already the case).
- Read access to the repo on the Mini (clone it there).

---

## 1. Container runtime

Use **OrbStack** (simplest on macOS, fast, low overhead, no Docker Desktop licensing) or
**Colima**. Either provides the `docker` + `docker compose` CLIs.

```bash
# OrbStack (recommended): install from https://orbstack.dev  (GUI installer)
# — or Colima:
brew install colima docker docker-compose
colima start --cpu 3 --memory 10 --disk 40    # caps the whole VM: 3 cores / 10 GB
```

Colima's `--cpu/--memory` is the **hard resource ceiling** for the entire stack — the
prototype's blast-radius control. OrbStack auto-manages resources; set a memory limit in its
settings if you want a hard cap.

---

## 2. Clone the repo on the Mini

```bash
git clone git@github.com:elavoaitx-max/AlphaGasIQ-Powered-by-Elavo-AI-.git ~/alphagasiq
cd ~/alphagasiq
```

---

## 3. Collapse the stack — `docker-compose.override.yml`

`docker compose` auto-merges an override file. Create this to (a) drop Redpanda — the event
bus already defaults to `memory` (`packages/config/config/settings.py: event_bus_impl="memory"`),
(b) keep Neo4j off (it's already behind the `neo4j` profile), and (c) set hard per-service
memory limits. Create `~/alphagasiq/docker-compose.override.yml`:

```yaml
name: alphagasiq

services:
  # Remove the Kafka dependency — the app runs on the in-memory bus by default.
  redpanda:
    deploy:
      replicas: 0          # don't start it
  api:
    environment:
      EVENT_BUS_IMPL: memory
      KAFKA_BOOTSTRAP_SERVERS: ""   # ensure nothing tries to reach Kafka
    mem_limit: 3g
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
  worker:
    environment:
      EVENT_BUS_IMPL: memory
      KAFKA_BOOTSTRAP_SERVERS: ""
    mem_limit: 2g
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
  web:
    mem_limit: 1g
  postgres:
    mem_limit: 2g
  redis:
    mem_limit: 512m
```

> `depends_on` is re-declared without the `redpanda` reference so removing Redpanda doesn't
> leave a dangling dependency. (The base compose only lists postgres/redis as api/worker deps,
> so this is belt-and-suspenders.)

### Apple Silicon note
The base compose uses `timescale/timescaledb-ha:pg16`. If that image fails to pull/run on
arm64, add under `postgres:` in the override either:
- `platform: linux/amd64` (runs via emulation — slower but works), **or**
- switch the image to `timescale/timescaledb:latest-pg16` (multi-arch).
Redis, Python (`node:20-slim`, `python` base) and the Next image are all multi-arch — fine.

---

## 4. Environment / secrets — `.env`

The stack **boots with no `.env`** (every value has a mock fallback; market data + news default
to `SIMULATED`). For the prototype you only need one real key to exercise the actual agents:

```bash
cp .env.example .env
```
Then set in `.env`:
```
ENVIRONMENT=production
ANTHROPIC_API_KEY=sk-ant-...        # real Claude agents (else agents run in mock/simulated mode)
# Change the default DB password from the compose default before exposing publicly:
# (also update the postgres service env + DATABASE_URL to match)
USE_MOCK_MARKET_DATA=true           # keep true for prototype (no CME/data vendor needed)
USE_MOCK_NEWS=true
```
Leave `EIA_API_KEY` / `NOAA_API_TOKEN` / `CME_*` blank for now — they report `not_configured`
and the mock providers take over, tagged `SIMULATED` end-to-end in the UI.

⚠️ **Change the default Postgres password** (`alphagasiq/alphagasiq`) before this is reachable
from the internet — set it in the `postgres` service env and `DATABASE_URL` together.

---

## 5. Fix the frontend API URL (build-time inlining) — REQUIRED

`NEXT_PUBLIC_API_URL` is inlined by Next.js **at build time**, but the web Dockerfile builds
with no such arg, so it bakes a `localhost:8000` default. Over the tunnel the browser would
call `localhost` and the app would be dead. Fix: make it a build arg.

**Patch `infrastructure/docker/Dockerfile.web`** — add before `RUN npm run build`:
```dockerfile
FROM node:20-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL=https://alphagasiq.elavoai.com/api/v1   # <-- add
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL                     # <-- add
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build
```

**Pass it from the override** — add to the `web` service in `docker-compose.override.yml`:
```yaml
  web:
    mem_limit: 1g
    build:
      context: apps/web
      dockerfile: ../../infrastructure/docker/Dockerfile.web
      args:
        NEXT_PUBLIC_API_URL: https://alphagasiq.elavoai.com/api/v1
```

This routes the browser → API under one hostname (`/api/v1` path). The tunnel (step 7) maps
that path to the api container. (Alternative: a second hostname `alphagasiq-api.elavoai.com`
→ api:8000, and set the arg to that; one hostname is simpler.)

---

## 6. Bring it up + verify (local first)

```bash
cd ~/alphagasiq
docker compose build
docker compose up -d
docker compose ps                 # postgres, redis, api, worker, web = up (NO redpanda/neo4j)
curl -s localhost:8000/health     # api healthy
open http://localhost:3000        # dashboard; dev sign-in: admin@alphagasiq.local / admin-dev-password
docker stats --no-stream          # confirm real RAM use to right-size the caps
```
Confirm the UI loads, shows `SIMULATED` data, and the recommendation → approve → paper-execute
→ close loop works before exposing it.

---

## 7. Publish via Cloudflare Tunnel

Outbound-only tunnel — no router ports, no home IP exposed.

```bash
brew install cloudflared
cloudflared tunnel login                          # authorize elavoai.com
cloudflared tunnel create alphagasiq
```
Create `~/.cloudflared/config.yml`:
```yaml
tunnel: alphagasiq
credentials-file: /Users/<you>/.cloudflared/<tunnel-id>.json
ingress:
  # API path first (more specific), then the web app.
  - hostname: alphagasiq.elavoai.com
    path: ^/api/.*
    service: http://localhost:8000
  - hostname: alphagasiq.elavoai.com
    service: http://localhost:3000
  - service: http_status:404
```
Route DNS + run it:
```bash
cloudflared tunnel route dns alphagasiq alphagasiq.elavoai.com
cloudflared tunnel run alphagasiq
```
Then `https://alphagasiq.elavoai.com` serves the app; `…/api/v1/*` hits the API. Cloudflare
terminates TLS. Add Cloudflare **Access** (Zero Trust) in front of the hostname if you want a
login wall while it's a private prototype.

---

## 8. Keep it running unattended (survive reboots / power blips)

- **Container stack:** every service already has `restart: unless-stopped`; ensure the container
  runtime starts at login — OrbStack: enable "Start at login"; Colima: `brew services start colima`.
- **Tunnel as a service:** `sudo cloudflared service install` (runs on boot).
- **macOS:** System Settings → Energy → "Start up automatically after a power failure"; disable
  sleep (`sudo pmset -a sleep 0 disksleep 0`).

---

## 9. Backups
- Nightly Postgres dump:
  ```bash
  docker compose exec -T postgres pg_dump -U alphagasiq alphagasiq | gzip > ~/agiq-backups/agiq_$(date +%F).sql.gz
  ```
  (cron/launchd it; keep ~14 days). The `pgdata` volume also persists across restarts.
- Time Machine on the Mini covers the repo + `.env` + tunnel creds.

---

## 10. Security checklist (home-hosted)
- ✅ Cloudflare Tunnel = no inbound ports open on the home network.
- ⬜ Change default Postgres password (step 4).
- ⬜ Change the dev sign-in creds / disable dev sign-in before any external user sees it.
- ⬜ Optionally gate behind Cloudflare Access while it's a private prototype.
- ✅ Paper-only: `PaperExecutionAdapter` is the only execution path (no live routing exists).
- Secrets live only in `~/alphagasiq/.env` on the Mini — not committed.

---

## 11. Deferred (not in the prototype)
- **OIDC SSO with ElavoAI** — unify login later (the app already speaks OIDC).
- **ElavoAI nav entry / "AlphaGasIQ" product card** linking to the subdomain.
- **Real data feeds** — add EIA/NOAA/CME/news keys when moving past mock/SIMULATED.
- **Neo4j pipeline digital twin** — `docker compose --profile neo4j up` if/when wanted.
- **Kafka/Redpanda** — only needed at multi-node scale; in-memory bus is fine for one box.
- **Migration to a cloud VM** — when it becomes customer-facing; same compose stack moves over.

---

## 12. Teardown
```bash
docker compose down            # stop (keep data volume)
docker compose down -v         # stop + delete data
cloudflared tunnel delete alphagasiq
```
Removing it leaves zero trace on the ElavoAI prod box — it was never there.

---

## 13. Upgrade from the admin portal

A super-admin **Upgrade** page (`/platform/admin/upgrade`) triggers a host-side
`git pull` + rebuild + restart, with a live log. The API never touches Docker or
git: it writes a trigger file into a shared `/deploy` volume; a host **launchd**
agent runs the actual upgrade and streams progress to a log the UI tails.

Requires the Mini's `~/alphagasiq` to be a **git clone** with a repo **deploy
key** installed (read-only is enough — it only pulls).

**1. Shared deploy dir + volume** — `mkdir -p ~/agiq-deploy`, and mount it into
the api service in `docker-compose.override.yml`:
```yaml
  api:
    volumes:
      - /Users/<you>/agiq-deploy:/deploy
```

**2. Host upgrade script** `~/agiq-upgrade.sh` (chmod +x): sets a homebrew PATH,
requires `~/agiq-deploy/trigger`, takes `upgrade.lock`, then
`git pull --ff-only` → `docker compose build` → `docker compose up -d` → health
check on `:8000/health`, logging each phase to `~/agiq-deploy/status.log` and
clearing the trigger/lock at the end. Bails (leaving the old build) on any
pull/build failure.

**3. launchd watcher** `~/Library/LaunchAgents/com.alphagasiq.upgrade.plist` with
`WatchPaths = [~/agiq-deploy/trigger]` running `/bin/bash ~/agiq-upgrade.sh`;
`launchctl load` it. Creating the trigger file fires the upgrade exactly once.

**4. App** — `routers/admin_upgrade.py` (POST writes the trigger, GET tails the
log, `GET /version` reports the version panel; SUPER_ADMIN-only
`admin.system_settings`) + the Upgrade admin page.

### 13.1 Version panel

The Upgrade page shows **Current** (the commit the running image was built from)
next to **Remote** (the newest commit on the tracked branch) and lists the
incoming commits, so an operator can see what an upgrade would actually bring in.

*Current* comes from `/app/build-info.json`, stamped by a throwaway `gitstamp`
stage in `Dockerfile.api` — it reports what is **executing**, not what the host
has checked out. That distinction is deliberate: a `git pull` with no rebuild
leaves old code running, and the panel must not hide that.

*Remote* comes from the GitHub API (`repos/{repo}/commits/{branch}` plus
`compare/{base}...{head}`), cached 60s. The repo is public, so no token is
needed; `GITHUB_TOKEN`, `UPGRADE_REPO` and `UPGRADE_BRANCH` are configurable in
the admin Configuration page under **Upgrade**.

⚠️ **The tracked branch is the whole story.** A fix pushed to a different branch
than the one this host pulls will never arrive, no matter how many times you
rebuild. The panel names the branch it is comparing against for exactly this
reason.

**Optional — surface "pulled but not rebuilt".** If `~/agiq-upgrade.sh` also
writes the host's checked-out commit into the shared deploy dir, the panel adds a
*Host checkout* warning whenever the working tree is ahead of the running image.
Add this to the script after the `git pull`:

```bash
git -C ~/alphagasiq log -1 --pretty=format:'%H%x00%s%x00%an%x00%cI' > /tmp/agiq-commit.raw
python3 -c "
import json
c, s, a, d = open('/tmp/agiq-commit.raw').read().split(chr(0))
json.dump({'commit': c, 'subject': s, 'author': a, 'committed_at': d},
          open('$HOME/agiq-deploy/checkout-info.json', 'w'))"
```

Without it the panel simply omits that row — `Current` vs `Remote` still work.
