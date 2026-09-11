# Docker Autoscaler

Single-host Docker orchestrator that continuously reconciles **desired state** vs **actual state** — a mini Kubernetes-style control loop for plain Docker.

The orchestrator is a **host-side FastAPI process**. Compose only runs the sidecars it calls: Redis, Traefik, and a locked-down Docker socket proxy. Demo replicas are created and removed by the orchestrator, not by Compose.

## What it does

- Polls container CPU / memory / network via the Docker stats API
- Smooths samples into a rolling average in Redis
- Scales a service up after 3 consecutive ticks above 80% CPU, down after 5 consecutive ticks below 30% CPU, with a cooldown so it cannot flap
- Creates and removes labelled replicas (`orchestrator.managed=true`)
- Traefik auto-discovers those replicas by Docker labels, so load balancing updates itself

## Stack

| Concern | Where it runs | Tool |
|---|---|---|
| Orchestrator API + control loop | host (`uvicorn`) | FastAPI |
| Docker control | Compose sidecar | `tecnativa/docker-socket-proxy` + docker-py |
| State / locks | Compose sidecar | Redis |
| Load balancing | Compose sidecar | Traefik v3 (label discovery) |
| Workload | containers created by the orchestrator | `scaler-demo`, `scaler-alpha`, `scaler-beta` |

## Prerequisites

- Docker Desktop 29+ / Docker Engine with Compose v2
- Python 3.12 (FastAPI 0.141 requires ≥3.10)

Images **cannot** be pulled through the socket proxy (`IMAGES=0` by design). Build the workload images locally before starting the orchestrator:

```bash
docker compose -f deploy/compose.yaml build demo alpha beta
```

Any extra image you add to `config/services.yml` must be pre-pulled on the host.

## Bring-up

1. Start sidecars and build the demo image:

```bash
docker compose -f deploy/compose.yaml build demo alpha beta
docker compose -f deploy/compose.yaml up -d redis traefik docker-socket-proxy
```

2. Confirm the proxy allows ping and refuses image listing:

```bash
curl -sS http://127.0.0.1:2375/_ping
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:2375/images/json
# expected: 200 then 403
```

3. Install the CLI and start the orchestrator on the host:

```bash
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
scaler start
scaler health
```

`scaler start` launches uvicorn in the background (PID file under `.scaler/`), bound to `0.0.0.0:8000` so LAN MQTT discovery can reach the API. There is **no auth** — treat the LAN as trusted. Override with `API_HOST` / `API_PORT`. Use `scaler stop` to terminate it **and stop/remove every orchestrator-managed replica** (`orch-*`). Sidecars (Redis, Traefik, socket proxy) stay up. You can still run `uvicorn scaler.main:app --host 0.0.0.0 --port 8000` in the foreground if you prefer; Ctrl+C also stops managed replicas.

On startup it reads desired state from Redis, lists containers labelled `orchestrator.managed=true`, and reconciles (creating `min_replicas` of `demo`, `alpha`, and `beta` if none exist).

`alpha` is a FastAPI CPU-burn app (like demo) at `/alpha`. `beta` is nginx at `/beta`. Scale them independently:

```bash
curl -sS -X POST http://127.0.0.1:8000/scale/alpha \
  -H 'content-type: application/json' -d '{"replicas": 2}'
curl -sS http://127.0.0.1/alpha/whoami
curl -sS http://127.0.0.1/beta/
scaler list
```

## CLI

```bash
scaler start                         # background orchestrator (PID + log under .scaler/)
scaler stop                          # stop orchestrator AND all orch-* replicas
scaler health                        # process (PID file) + GET /health (Redis + Docker)
scaler list                          # all managed containers
scaler list orch-demo-0              # details for one container
scaler log orch-demo-0               # logs (alias: scaler logs)
scaler log orch-demo-0 --tail 50
scaler service stop demo             # stop one service's replicas
scaler service start demo            # start one service's replicas
```

Base URL defaults to `http://127.0.0.1:8000`. Override with `--url` or `SCALER_API_URL`. PID file override: `SCALER_PID_FILE`. The Docker image also ships the `scaler` console script.

## MQTT (optional)

The orchestrator is the only MQTT client. The host (demo/alpha/beta) appears as one device.

On a LAN, this Mac **advertises** `_scaler._tcp` (Bonjour) so the MQTT server Mac can discover it, and with `MQTT_HOST=mdns` it **browses** `_mqtt._tcp` for the broker.

```bash
# .env on this Mac
MQTT_HOST=mdns
MQTT_PORT=1883
MQTT_DEVICE_ID=scaler-hw-01
MQTT_MDNS=true
```

On the **broker Mac**, Mosquitto must listen on the LAN (`0.0.0.0:1883`) and advertise itself:

```bash
# keep this running on the broker Mac
dns-sd -R "mosquitto" _mqtt._tcp local 1883
```

Find this orchestrator from the broker Mac:

```bash
dns-sd -B _scaler._tcp
```

Or set `MQTT_HOST=192.168.x.x` to skip mDNS and connect by IP.

| Topic | Direction |
|---|---|
| `devices/{id}/discovery` | retained device card (id, ip, api, topics) |
| `devices/{id}/status` | retained telemetry |
| `devices/{id}/events` | scale / reconcile events |
| `devices/{id}/lwt` | `online` / `offline` (LWT) |
| `devices/{id}/cmd` | commands from the server |

Commands:

```json
{"action":"scale","service":"alpha","replicas":2}
{"action":"stop"}
{"action":"start"}
{"action":"stop","service":"demo"}
{"action":"start","service":"demo"}
{"action":"add_service","service":"gamma","image":"scaler-gamma:latest"}
{"action":"remove_service","service":"gamma"}
```

`stop` / `start` without `service` apply to the whole host: host `stop` (MQTT or `POST /containers/stop-all`) sets `desired=0` for every service then kills replicas so the tick loop will not recreate them. Host `start` restores each stopped service to `min_replicas`. With `service`, only that workload is drained or brought back. `add_service` / `remove_service` manage extra services on this HW at runtime (YAML services in `config/services.yml` can be stopped, not deleted).

MQTT events publish immediately. Retained `devices/{id}/status` is also refreshed immediately after start/stop/scale (and again after each 5s tick for CPU/metrics).

A down broker does not stop local scaling; the client retries with backoff. `GET /health` returns 200 only if Redis and Docker respond; MQTT is reported as `connected` / `disconnected` / `disabled` and does not fail the probe.

API:

```bash
curl -sS http://127.0.0.1:8000/health | python3 -m json.tool
curl -sS http://127.0.0.1:8000/status | python3 -m json.tool
curl -sS -X POST http://127.0.0.1:8000/scale/demo \
  -H 'content-type: application/json' \
  -d '{"replicas": 3}'
curl -sS -X POST http://127.0.0.1:8000/services \
  -H 'content-type: application/json' \
  -d '{"name":"gamma","image":"scaler-gamma:latest"}'
curl -sS -X POST http://127.0.0.1:8000/services/gamma/stop
curl -sS -X POST http://127.0.0.1:8000/services/gamma/start
curl -sS -X DELETE http://127.0.0.1:8000/services/gamma
```

Live events:

```bash
python3 - <<'PY'
import asyncio, json, websockets
async def main():
    async with websockets.connect("ws://127.0.0.1:8000/events") as ws:
        async for raw in ws:
            print(json.loads(raw))
asyncio.run(main())
PY
```

Drive CPU on the demo app (Traefik listens on port 80, prefix `/demo`):

```bash
for i in $(seq 1 40); do curl -sS "http://127.0.0.1/demo/burn?seconds=1" >/dev/null & done
wait
```

After 3 high ticks the engine raises desired replicas; after load stops and 5 low ticks (plus cooldown) it scales back down. Watch `GET /status` and `WS /events`.

Prometheus scrape: `http://127.0.0.1:8000/metrics`  
Traefik dashboard: `http://127.0.0.1:8080`

## Tests

```bash
source .venv/bin/activate
pytest
```

## Layout

```
src/scaler/     orchestrator package (API, controller, Docker adapter, Redis, MQTT)
config/         per-service policy + container template
deploy/         Compose sidecars and optional orchestrator Dockerfile
workloads/      images the controller creates (demo, alpha, beta)
tests/          pytest suite mirroring the package
```

`POST /scale/{service}` is idempotent: it only writes the desired replica count. The reconciler creates or removes containers until actual matches desired, so repeating `{replicas: 3}` does not spawn duplicates.
