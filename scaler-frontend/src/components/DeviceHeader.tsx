import type { DeviceDiscovery, DeviceOnlineStatus } from "../types/status";

interface DeviceHeaderProps {
  deviceStatus: DeviceOnlineStatus;
  discovery?: DeviceDiscovery | null;
}

export function DeviceHeader({
  deviceStatus,
  discovery = null,
}: DeviceHeaderProps) {
  const online = deviceStatus === "online";

  return (
    <header className="welcome">
      <span
        className={`status-badge ${online ? "status-badge--success" : "status-badge--danger"}`}
        role="status"
      >
        <span className="status-badge__dot" aria-hidden="true" />
        {deviceStatus}
      </span>
      {discovery ? (
        <div className="welcome__meta">
          <span>
            LAN <code>{discovery.ip}</code>
          </span>
          <a href={discovery.api} target="_blank" rel="noreferrer">
            {discovery.api}
          </a>
          <span>
            <code>{discovery.topics.status}</code>
          </span>
        </div>
      ) : (
        <p className="welcome__meta">Waiting for discovery retained message…</p>
      )}
    </header>
  );
}
