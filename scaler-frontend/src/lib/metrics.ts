import type { DeviceStatus, ServiceStatus } from "../types/status";
import { deriveServiceFields } from "../types/status";

export function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[unit]}`;
}

export function formatCpu(value: number | null): string {
  if (value === null) return "—";
  return `${value.toFixed(1)}%`;
}

export function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

export function fleetTotals(status: DeviceStatus) {
  return status.services.reduce(
    (acc, service) => {
      acc.desired += service.desired_replicas;
      acc.actual += service.actual_replicas;
      acc.healthy += service.healthy;
      return acc;
    },
    { desired: 0, actual: 0, healthy: 0, serviceCount: status.services.length },
  );
}

export function isServiceUnhealthy(service: ServiceStatus): boolean {
  const { scale_gap } = deriveServiceFields(service);
  return service.healthy < service.actual_replicas || scale_gap !== 0;
}

export type ServiceBorderStatus = "ok" | "warn" | "danger" | "idle";

/** Border tone for the service card visual. */
export function serviceBorderStatus(service: ServiceStatus): ServiceBorderStatus {
  const { scale_gap, cooldown_active } = deriveServiceFields(service);
  const stopped =
    service.desired_replicas === 0 && service.actual_replicas === 0;

  if (stopped) return "idle";
  if (service.healthy < service.actual_replicas) return "danger";
  if (scale_gap !== 0 || cooldown_active) return "warn";
  return "ok";
}
