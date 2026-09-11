import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";
import mqtt from "mqtt";
import type {
  DeviceCommand,
  DeviceDiscovery,
  DeviceStatus,
  LiveDeviceSnapshot,
} from "../src/types/status";

export interface MqttBridgeOptions {
  brokerUrl?: string;
  deviceId?: string;
}

interface BridgeState {
  brokerConnected: boolean;
  deviceId: string;
  discoveryTopic: string;
  discovery: DeviceDiscovery | null;
  status: DeviceStatus | null;
  lwt: string | null;
  error: string | null;
  lastUpdatedAt: number | null;
  subscribedTopics: Set<string>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

function parseDiscovery(value: unknown): DeviceDiscovery | null {
  if (!isRecord(value)) return null;
  if (typeof value.device_id !== "string") return null;
  if (value["device-status"] !== "online" && value["device-status"] !== "offline") {
    return null;
  }
  if (typeof value.ip !== "string" || typeof value.api !== "string") return null;
  if (!isRecord(value.topics)) return null;
  const topics = value.topics;
  if (
    typeof topics.status !== "string" ||
    typeof topics.events !== "string" ||
    typeof topics.cmd !== "string" ||
    typeof topics.lwt !== "string"
  ) {
    return null;
  }
  return {
    device_id: value.device_id,
    "device-status": value["device-status"],
    ip: value.ip,
    api: value.api,
    topics: {
      status: topics.status,
      events: topics.events,
      cmd: topics.cmd,
      lwt: topics.lwt,
    },
  };
}

function parseStatus(value: unknown): DeviceStatus | null {
  if (!isRecord(value)) return null;
  if (typeof value.device_id !== "string") return null;
  if (value["device-status"] !== "online" && value["device-status"] !== "offline") {
    return null;
  }
  if (!Array.isArray(value.services)) return null;
  return value as unknown as DeviceStatus;
}

function parseCommand(value: unknown): DeviceCommand | null {
  if (!isRecord(value)) return null;
  const action = value.action;
  if (action !== "start" && action !== "stop" && action !== "scale") {
    return null;
  }

  const command: DeviceCommand = { action };

  if (typeof value.service === "string" && value.service.trim()) {
    command.service = value.service.trim();
  }

  if (action === "scale") {
    if (typeof value.replicas !== "number" || !Number.isInteger(value.replicas) || value.replicas < 0) {
      return null;
    }
    if (!command.service) return null;
    command.replicas = value.replicas;
  }

  return command;
}

function snapshotFrom(state: BridgeState): LiveDeviceSnapshot {
  return {
    brokerConnected: state.brokerConnected,
    deviceId: state.deviceId,
    discoveryTopic: state.discoveryTopic,
    discovery: state.discovery,
    status: state.status,
    lwt: state.lwt,
    error: state.error,
    lastUpdatedAt: state.lastUpdatedAt,
  };
}

function sendJson(res: ServerResponse, statusCode: number, body: unknown) {
  res.statusCode = statusCode;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
}

function readJsonBody(req: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => {
      chunks.push(chunk);
      if (chunks.reduce((n, c) => n + c.length, 0) > 64_000) {
        reject(new Error("Request body too large"));
        req.destroy();
      }
    });
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8").trim();
      if (!raw) {
        resolve(null);
        return;
      }
      try {
        resolve(JSON.parse(raw) as unknown);
      } catch {
        reject(new Error("Invalid JSON body"));
      }
    });
    req.on("error", reject);
  });
}

/**
 * Server-side MQTT bridge. Browsers cannot speak MQTT/TCP on :1883, so Vite
 * subscribes to discovery → status/lwt and exposes `GET /api/live` plus
 * `POST /api/cmd` for start/stop/scale.
 */
export function mqttLiveBridge(options: MqttBridgeOptions = {}): Plugin {
  const brokerUrl =
    options.brokerUrl ||
    process.env.MQTT_URL?.trim() ||
    "mqtt://127.0.0.1:1883";
  const deviceId =
    options.deviceId ||
    process.env.MQTT_DEVICE_ID?.trim() ||
    process.env.VITE_DEVICE_ID?.trim() ||
    "scaler-hw-01";
  const discoveryTopic = `devices/${deviceId}/discovery`;

  const state: BridgeState = {
    brokerConnected: false,
    deviceId,
    discoveryTopic,
    discovery: null,
    status: null,
    lwt: null,
    error: null,
    lastUpdatedAt: null,
    subscribedTopics: new Set([discoveryTopic]),
  };

  let client: mqtt.MqttClient | null = null;

  const touch = () => {
    state.lastUpdatedAt = Date.now();
  };

  const ensureSubscriptions = (discovery: DeviceDiscovery) => {
    if (!client) return;
    for (const topic of [discovery.topics.status, discovery.topics.lwt]) {
      if (state.subscribedTopics.has(topic)) continue;
      client.subscribe(topic, { qos: 0 }, (err) => {
        if (err) {
          state.error = `Failed to subscribe ${topic}: ${err.message}`;
          return;
        }
        state.subscribedTopics.add(topic);
      });
    }
  };

  const publishCommand = (command: DeviceCommand): Promise<void> => {
    return new Promise((resolve, reject) => {
      if (!client || !state.brokerConnected) {
        reject(new Error("MQTT broker is not connected"));
        return;
      }
      const topic =
        state.discovery?.topics.cmd ?? `devices/${state.deviceId}/cmd`;
      client.publish(topic, JSON.stringify(command), { qos: 1, retain: false }, (err) => {
        if (err) {
          reject(err);
          return;
        }
        resolve();
      });
    });
  };

  const startClient = () => {
    if (client) return;

    client = mqtt.connect(brokerUrl, {
      reconnectPeriod: 2_000,
      connectTimeout: 10_000,
      clientId: `scalar-dashboard-${deviceId}-${Math.random().toString(16).slice(2, 8)}`,
    });

    client.on("connect", () => {
      state.brokerConnected = true;
      state.error = null;
      touch();
      client?.subscribe(discoveryTopic, { qos: 0 }, (err) => {
        if (err) {
          state.error = `Failed to subscribe ${discoveryTopic}: ${err.message}`;
        }
      });
      if (state.discovery) {
        ensureSubscriptions(state.discovery);
      }
    });

    client.on("reconnect", () => {
      state.brokerConnected = false;
      touch();
    });

    client.on("close", () => {
      state.brokerConnected = false;
      touch();
    });

    client.on("error", (err) => {
      state.error = err.message;
      touch();
    });

    client.on("message", (topic, payload) => {
      const text = payload.toString("utf8");
      touch();

      if (topic === discoveryTopic) {
        try {
          const discovery = parseDiscovery(JSON.parse(text) as unknown);
          if (!discovery) {
            state.error = "Invalid discovery payload";
            return;
          }
          state.discovery = discovery;
          state.error = null;
          ensureSubscriptions(discovery);
        } catch (err) {
          state.error =
            err instanceof Error
              ? `Discovery parse error: ${err.message}`
              : "Discovery parse error";
        }
        return;
      }

      const topics = state.discovery?.topics;
      if (topics && topic === topics.status) {
        try {
          const status = parseStatus(JSON.parse(text) as unknown);
          if (!status) {
            state.error = "Invalid status payload";
            return;
          }
          state.status = status;
          state.error = null;
        } catch (err) {
          state.error =
            err instanceof Error
              ? `Status parse error: ${err.message}`
              : "Status parse error";
        }
        return;
      }

      if (topics && topic === topics.lwt) {
        state.lwt = text.trim();
        state.error = null;
      }
    });
  };

  const stopClient = () => {
    if (!client) return;
    client.end(true);
    client = null;
    state.brokerConnected = false;
  };

  const apiMiddleware = (
    req: IncomingMessage,
    res: ServerResponse,
    next: (err?: unknown) => void,
  ) => {
    const url = req.url?.split("?")[0];

    if (req.method === "GET" && url === "/api/live") {
      sendJson(res, 200, snapshotFrom(state));
      return;
    }

    if (req.method === "POST" && url === "/api/cmd") {
      void readJsonBody(req)
        .then(async (body) => {
          const command = parseCommand(body);
          if (!command) {
            sendJson(res, 400, {
              error:
                'Invalid command. Use {"action":"start"|"stop","service":"..."} or {"action":"scale","service":"...","replicas":n}',
            });
            return;
          }
          await publishCommand(command);
          sendJson(res, 200, { ok: true, command });
        })
        .catch((err: unknown) => {
          const message =
            err instanceof Error ? err.message : "Failed to publish command";
          sendJson(res, 502, { error: message });
        });
      return;
    }

    next();
  };

  return {
    name: "mqtt-live-bridge",
    configureServer(server) {
      startClient();
      server.middlewares.use(apiMiddleware);

      const exit = () => stopClient();
      process.once("exit", exit);
      process.once("SIGINT", exit);
      process.once("SIGTERM", exit);
    },
    configurePreviewServer(server) {
      startClient();
      server.middlewares.use(apiMiddleware);
    },
  };
}
