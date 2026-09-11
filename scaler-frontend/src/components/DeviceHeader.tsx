import type { DeviceDiscovery, DeviceOnlineStatus } from "../types/status";

interface DeviceHeaderProps {
  deviceId: string;
  deviceStatus: DeviceOnlineStatus;
  discovery?: DeviceDiscovery | null;
}

export function DeviceHeader({
  deviceId,
  deviceStatus,
  discovery = null,
}: DeviceHeaderProps) {
  const online = deviceStatus === "online";

  return (
    <header className="device-header">
      <div className="device-header__brand">
        <p className="eyebrow">Scalar · discovery</p>
        <h1>{deviceId}</h1>
        {discovery ? (
          <dl className="device-header__meta">
            <div>
              <dt>LAN IP</dt>
              <dd>
                <code>{discovery.ip}</code>
              </dd>
            </div>
            <div>
              <dt>API</dt>
              <dd>
                <a href={discovery.api} target="_blank" rel="noreferrer">
                  {discovery.api}
                </a>
              </dd>
            </div>
            <div>
              <dt>Status topic</dt>
              <dd>
                <code>{discovery.topics.status}</code>
              </dd>
            </div>
            <div>
              <dt>LWT topic</dt>
              <dd>
                <code>{discovery.topics.lwt}</code>
              </dd>
            </div>
          </dl>
        ) : (
          <p className="device-header__waiting">
            Waiting for discovery retained message…
          </p>
        )}
      </div>
      <span
        className={`status-badge ${online ? "status-badge--success" : "status-badge--danger"}`}
        role="status"
      >
        <span className="status-badge__dot" aria-hidden="true" />
        {deviceStatus}
      </span>
    </header>
  );
}
