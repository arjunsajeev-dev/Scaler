import { useEffect, useState } from "react";
import { DeviceHeader } from "./components/DeviceHeader";
import { FleetSummary } from "./components/FleetSummary";
import { ReplicaTable } from "./components/ReplicaTable";
import { ServiceGrid } from "./components/ServiceGrid";
import { useLiveDevice } from "./hooks/useLiveDevice";
import { fleetTotals } from "./lib/metrics";
import { resolveOnlineStatus } from "./types/status";

export function App() {
  const { snapshot, error, isRefreshing } = useLiveDevice();
  const [selectedIndex, setSelectedIndex] = useState(0);

  const status = snapshot?.status ?? null;
  const discovery = snapshot?.discovery ?? null;

  useEffect(() => {
    if (!status) return;
    setSelectedIndex((current) =>
      Math.min(current, Math.max(status.services.length - 1, 0)),
    );
  }, [status]);

  if (!snapshot) {
    return (
      <div className="app-shell">
        <div className="app-shell__glow" aria-hidden="true" />
        <main className="dashboard dashboard--state">
          <p className="load-state">
            {error
              ? `Unable to reach MQTT bridge: ${error}`
              : "Connecting to MQTT bridge…"}
          </p>
        </main>
      </div>
    );
  }

  const deviceId =
    discovery?.device_id ?? status?.device_id ?? snapshot.deviceId;
  const deviceStatus = resolveOnlineStatus(snapshot);
  const totals = status
    ? fleetTotals(status)
    : { serviceCount: 0, desired: 0, actual: 0, healthy: 0 };
  const selectedService =
    status?.services[selectedIndex] ?? status?.services[0] ?? null;
  const updatedLabel =
    snapshot.lastUpdatedAt === null
      ? null
      : new Date(snapshot.lastUpdatedAt).toLocaleTimeString();

  return (
    <div className="app-shell">
      <div className="app-shell__glow" aria-hidden="true" />
      <main className="dashboard">
        <DeviceHeader
          deviceId={deviceId}
          deviceStatus={deviceStatus}
          discovery={discovery}
        />
        <div className="poll-meta" aria-live="polite">
          <span>
            {snapshot.brokerConnected ? "MQTT connected" : "MQTT reconnecting"}
            {" · "}
            {isRefreshing ? "Refreshing…" : "Live"} · every 5s
            {updatedLabel ? ` · bridge ${updatedLabel}` : null}
          </span>
          {error ? <span className="poll-meta__error">{error}</span> : null}
        </div>
        {status ? (
          <>
            <FleetSummary
              serviceCount={totals.serviceCount}
              desired={totals.desired}
              actual={totals.actual}
              healthy={totals.healthy}
            />
            <ServiceGrid
              services={status.services}
              selectedIndex={selectedIndex}
              onSelect={setSelectedIndex}
              commandsEnabled={snapshot.brokerConnected}
            />
            {selectedService ? (
              <ReplicaTable service={selectedService} />
            ) : null}
          </>
        ) : (
          <p className="load-state load-state--inline">
            Discovery received
            {discovery ? ` (${discovery.topics.status})` : ""}. Waiting for
            status retained message…
          </p>
        )}
      </main>
    </div>
  );
}
