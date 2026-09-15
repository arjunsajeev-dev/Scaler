import { useEffect, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { sampleDeviceStatus } from "./data/sampleStatus";
import { useLiveDevice } from "./hooks/useLiveDevice";
import { fleetTotals } from "./lib/metrics";
import { DashboardScreen } from "./screens/DashboardScreen";
import { ReplicasScreen } from "./screens/ReplicasScreen";
import { ServicesScreen } from "./screens/ServicesScreen";
import type { AppScreen } from "./screens/types";
import { resolveOnlineStatus } from "./types/status";

const SCREEN_LABEL: Record<AppScreen, string> = {
  dashboard: "Dashboard",
  services: "Services",
  replicas: "Replicas",
};

export function App() {
  const { snapshot, error, isRefreshing } = useLiveDevice();
  const [screen, setScreen] = useState<AppScreen>("dashboard");
  const [selectedIndex, setSelectedIndex] = useState(0);

  const liveStatus = snapshot?.status ?? null;
  const useSample =
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).has("sample");
  const status = liveStatus ?? (useSample ? sampleDeviceStatus : null);
  const discovery = snapshot?.discovery ?? null;
  const services = status?.services ?? [];

  useEffect(() => {
    if (!status) return;
    setSelectedIndex((current) =>
      Math.min(current, Math.max(status.services.length - 1, 0)),
    );
  }, [status]);

  const deviceId =
    discovery?.device_id ?? status?.device_id ?? snapshot?.deviceId ?? "scaler";
  const updatedLabel =
    snapshot?.lastUpdatedAt == null
      ? null
      : new Date(snapshot.lastUpdatedAt).toLocaleTimeString();
  const waitingMessage = discovery
    ? `Discovery received (${discovery.topics.status}). Waiting for status retained message…`
    : "Waiting for MQTT discovery and status…";

  const commandsEnabled =
    (snapshot?.brokerConnected ?? false) || (snapshot?.apiReachable ?? false);
  const linkLabel = snapshot?.brokerConnected
    ? "MQTT connected"
    : snapshot?.apiReachable
      ? "API connected"
      : "MQTT reconnecting";

  const sidebar = (
    <Sidebar
      deviceId={deviceId}
      screen={screen}
      onNavigate={setScreen}
      services={services}
      selectedIndex={selectedIndex}
      onSelectService={setSelectedIndex}
      brokerConnected={snapshot?.brokerConnected ?? false}
      apiReachable={snapshot?.apiReachable ?? false}
      isRefreshing={isRefreshing}
      updatedLabel={updatedLabel}
    />
  );

  if (!snapshot) {
    return (
      <div className="app-page">
        <div className="app-frame">
          {sidebar}
          <div className="main">
            <p className="page-kicker">{SCREEN_LABEL[screen]}</p>
            <main className="dashboard--state">
              <p className="load-state">
                {error
                  ? `Unable to reach MQTT bridge: ${error}`
                  : "Connecting to MQTT bridge…"}
              </p>
            </main>
          </div>
        </div>
      </div>
    );
  }

  const deviceStatus = resolveOnlineStatus(snapshot);
  const totals = status
    ? fleetTotals(status)
    : { serviceCount: 0, desired: 0, actual: 0, healthy: 0 };
  const selectedService =
    status?.services[selectedIndex] ?? status?.services[0] ?? null;

  return (
    <div className="app-page">
      <div className="app-frame">
        {sidebar}
        <div className="main">
          <p className="page-kicker">{SCREEN_LABEL[screen]}</p>
          <p className="poll-meta" aria-live="polite">
            {linkLabel}
            {" · "}
            {isRefreshing ? "Refreshing…" : "Live"} · every 5s
            {updatedLabel ? ` · bridge ${updatedLabel}` : null}
            {error && !snapshot.apiReachable ? (
              <span className="poll-meta__error">{error}</span>
            ) : null}
          </p>
          {screen === "dashboard" ? (
            <DashboardScreen
              deviceStatus={deviceStatus}
              discovery={discovery}
              status={status}
              totals={totals}
              waitingMessage={waitingMessage}
            />
          ) : null}
          {screen === "services" ? (
            <ServicesScreen
              services={services}
              selectedIndex={selectedIndex}
              onSelect={setSelectedIndex}
              commandsEnabled={commandsEnabled}
              waitingMessage={waitingMessage}
            />
          ) : null}
          {screen === "replicas" ? (
            <ReplicasScreen
              service={selectedService}
              waitingMessage={
                services.length === 0
                  ? waitingMessage
                  : "Select a service from the sidebar."
              }
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
