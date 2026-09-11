/** MQTT retained payload on `devices/{device_id}/discovery`. */
export interface DeviceDiscovery {
  device_id: string;
  "device-status": DeviceOnlineStatus;
  ip: string;
  /** Base HTTP API URL advertised by the device. */
  api: string;
  topics: DeviceTopicMap;
}

export interface DeviceTopicMap {
  status: string;
  events: string;
  cmd: string;
  lwt: string;
}

/** MQTT retained payload on `devices/{device_id}/status`. */
export interface DeviceStatus {
  device_id: string;
  /** Hyphenated key as published on the wire (not `device_status`). */
  "device-status": DeviceOnlineStatus;
  services: ServiceStatus[];
}

export type DeviceOnlineStatus = "online" | "offline";

export type DeviceCmdAction = "start" | "stop" | "scale";

/** Command published to `devices/{device_id}/cmd`. */
export interface DeviceCommand {
  action: DeviceCmdAction;
  service?: string;
  replicas?: number;
}

/** Aggregated view from the Vite MQTT bridge (`GET /api/live`). */
export interface LiveDeviceSnapshot {
  brokerConnected: boolean;
  deviceId: string;
  discoveryTopic: string;
  discovery: DeviceDiscovery | null;
  status: DeviceStatus | null;
  lwt: string | null;
  error: string | null;
  lastUpdatedAt: number | null;
}

export function resolveOnlineStatus(
  snapshot: Pick<LiveDeviceSnapshot, "lwt" | "discovery" | "status">,
): DeviceOnlineStatus {
  const fromLwt = normalizeOnline(snapshot.lwt);
  if (fromLwt) return fromLwt;
  if (snapshot.discovery?.["device-status"]) {
    return snapshot.discovery["device-status"];
  }
  if (snapshot.status?.["device-status"]) {
    return snapshot.status["device-status"];
  }
  return "offline";
}

function normalizeOnline(value: string | null | undefined): DeviceOnlineStatus | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase();
  if (normalized === "online") return "online";
  if (normalized === "offline") return "offline";
  return null;
}
export interface ServiceStatus {
  name: string;
  desired_replicas: number;
  actual_replicas: number;
  healthy: number;
  /** Raw average CPU as published; do not assume a 0–100 scale. */
  avg_cpu: number;
  avg_memory_bytes: number;
  consecutive_high: number;
  consecutive_low: number;
  cooldown_remaining_seconds: number;
  replicas: ReplicaStatus[];
}

export interface ReplicaStatus {
  id: string;
  name: string;
  index: number;
  status: string;
  cpu_percent: number | null;
  memory_bytes: number | null;
  net_rx_bytes: number | null;
  net_tx_bytes: number | null;
}

/** Per-service values computed in the UI, not present on the MQTT payload. */
export interface ServiceDerivedFields {
  scale_gap: number;
  health_ratio: number;
  memory_mb: number;
  cooldown_active: boolean;
}

export type CompositionWidget =
  | "DeviceHeader"
  | "FleetSummary"
  | "ServiceGrid"
  | "ReplicaTable";

export type WidgetType =
  | "DeviceHeader"
  | "FleetSummary"
  | "ServiceCard"
  | "ReplicaTable";

export type BindingSource = "payload" | "derived" | "aggregate";

export interface DerivedField {
  scope: "service";
  expression: string;
  description?: string;
}

export interface VisualRule {
  id: string;
  widget: WidgetType;
  when: string;
  apply: Record<string, unknown>;
}

export interface WidgetBinding {
  field: string;
  /** JSON Pointer into DeviceStatus. `{i}` is the service index. */
  pointer: string;
  source: BindingSource;
}

export interface DashboardWidget {
  id: string;
  type: WidgetType;
  /** JSON Pointer to an array to iterate, e.g. `/services`. */
  repeat: string | null;
  bindings: WidgetBinding[];
}

export interface DashboardUiSchema {
  id: string;
  title: string;
  payloadSchema: string;
  composition: CompositionWidget[];
  derivedFields: Record<string, DerivedField>;
  visualRules: VisualRule[];
  widgets: DashboardWidget[];
}

export function scaleGap(service: ServiceStatus): number {
  return service.desired_replicas - service.actual_replicas;
}

export function healthRatio(service: ServiceStatus): number {
  return service.healthy / Math.max(service.actual_replicas, 1);
}

export function memoryMb(service: ServiceStatus): number {
  return service.avg_memory_bytes / 1_048_576;
}

export function cooldownActive(service: ServiceStatus): boolean {
  return service.cooldown_remaining_seconds > 0;
}

export function deriveServiceFields(service: ServiceStatus): ServiceDerivedFields {
  return {
    scale_gap: scaleGap(service),
    health_ratio: healthRatio(service),
    memory_mb: memoryMb(service),
    cooldown_active: cooldownActive(service),
  };
}
