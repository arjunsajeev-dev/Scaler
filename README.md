# Scaler

Single-host Docker orchestrator with a live fleet dashboard.

The host process reconciles **desired vs actual** replicas (a small Kubernetes-style control loop for plain Docker). It publishes status over MQTT and advertises itself on the LAN via mDNS. The dashboard follows that device and can send scale / start / stop commands.

There is **no auth**. Treat the LAN as trusted.

```
                    MQTT broker
                         │
     ┌───────────────────┼───────────────────┐
     │                   │                   │
scaler-client        topics              scaler-frontend
(orchestrator)   devices/{id}/*          (Vite + MQTT bridge)
     │                                       │
  Redis / Traefik / Docker socket proxy      browser :5173
```

## Layout

| Path | What it is |
|---|---|
| [`scaler-client/`](scaler-client/) | Host-side FastAPI orchestrator, CLI, Compose sidecars, workload images |
| [`scaler-frontend/`](scaler-frontend/) | React dashboard. Vite plugin bridges MQTT (browsers cannot speak MQTT TCP) |

## Prerequisites

- Docker Desktop 29+ / Docker Engine with Compose v2
- Python 3.12
- Node.js 22+ (for the dashboard)
- An MQTT broker on the LAN (Mosquitto). Optional if you only use the HTTP API.

## Quick start

### 1. Orchestrator

```bash
cd scaler-client
cp .env.example .env

docker compose -f deploy/compose.yaml build demo alpha beta
docker compose -f deploy/compose.yaml up -d redis traefik docker-socket-proxy

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
scaler start
scaler health
```

`scaler start` binds `0.0.0.0:8000`. Workload images cannot be pulled through the socket proxy (`IMAGES=0`); build them locally first.

Sidecars stay up after `scaler stop`. That command also removes every orchestrator-managed replica (`orch-*`).

Full CLI, scaling policy, MQTT topics, and API: [scaler-client/README.md](scaler-client/README.md).

### 2. Dashboard

Needs a reachable MQTT broker and a running orchestrator that publishes `devices/{id}/status`.

```bash
cd scaler-frontend
cp .env.example .env
# MQTT_URL=mqtt://127.0.0.1:1883
# MQTT_DEVICE_ID=scaler-hw-01

npm install
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). The page polls the Vite MQTT bridge every 5s and shows device online/offline, services, replica counts, and controls to start / stop / scale.

From another Mac, point `MQTT_URL` at the broker host, for example `mqtt://192.168.x.x:1883`.

## Ports

| Port | Service |
|---|---|
| 8000 | Orchestrator API (`GET /health`, `GET /status`, `POST /scale/{service}`) |
| 80 | Traefik → workloads (`/demo`, `/alpha`, `/beta`) |
| 8080 | Traefik dashboard |
| 6379 | Redis (localhost only) |
| 2375 | Docker socket proxy (localhost only) |
| 1883 | MQTT broker |
| 5173 | Dashboard (Vite) |

Prometheus scrape: `http://127.0.0.1:8000/metrics`

## MQTT

The orchestrator is the MQTT client. The whole host appears as one device (`MQTT_DEVICE_ID`, default `scaler-hw-01`).

On a LAN it advertises `_scaler._tcp` and, with `MQTT_HOST=mdns`, browses `_mqtt._tcp` for the broker.

| Topic | Direction |
|---|---|
| `devices/{id}/discovery` | retained device card |
| `devices/{id}/status` | retained telemetry |
| `devices/{id}/events` | scale / reconcile events |
| `devices/{id}/lwt` | `online` / `offline` |
| `devices/{id}/cmd` | commands from the dashboard / server |

```json
{"action":"scale","service":"alpha","replicas":2}
{"action":"stop"}
{"action":"start"}
{"action":"stop","service":"demo"}
{"action":"start","service":"demo"}
```

A down broker does not stop local scaling. `GET /health` still returns 200 if Redis and Docker are up; MQTT is reported as `connected` / `disconnected` / `disabled`.

## Tests

```bash
cd scaler-client
source .venv/bin/activate
pytest
```
