import type { ServiceStatus } from "../types/status";
import { serviceBorderStatus } from "../lib/metrics";
import type { AppScreen } from "../screens/types";

interface SidebarProps {
  deviceId: string;
  screen: AppScreen;
  onNavigate: (screen: AppScreen) => void;
  services: ServiceStatus[];
  selectedIndex: number;
  onSelectService: (index: number) => void;
  brokerConnected: boolean;
  apiReachable: boolean;
  isRefreshing: boolean;
  updatedLabel: string | null;
}

function IconMoon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M13 9.2A5.2 5.2 0 0 1 6.8 3 5.4 5.4 0 1 0 13 9.2Z"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconGrid() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="2" y="2" width="5" height="5" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
      <rect x="9" y="2" width="5" height="5" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
      <rect x="2" y="9" width="5" height="5" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
      <rect x="9" y="9" width="5" height="5" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

function IconLayers() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M2 5.5 8 3l6 2.5L8 8 2 5.5Z"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
      <path d="M2 8.5 8 11l6-2.5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M2 11.5 8 14l6-2.5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

function IconTable() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="2" y="3" width="12" height="10" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M2 6.5h12M8 6.5v6.5" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

function IconSignal() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M3 11.5c2.6-2.6 7.4-2.6 10 0"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <path
        d="M5.2 9.3a4.4 4.4 0 0 1 5.6 0"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <circle cx="8" cy="12.4" r="0.9" fill="currentColor" />
    </svg>
  );
}

export function Sidebar({
  deviceId,
  screen,
  onNavigate,
  services,
  selectedIndex,
  onSelectService,
  brokerConnected,
  apiReachable,
  isRefreshing,
  updatedLabel,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <button type="button" className="sidebar__brand" onClick={() => onNavigate("dashboard")}>
        <span className="sidebar__mark">
          <IconMoon />
        </span>
        <span className="sidebar__brand-copy">
          <span className="sidebar__brand-name">Scaler</span>
          <span className="sidebar__brand-id">{deviceId}</span>
        </span>
        <span className="sidebar__chevron" aria-hidden="true">
          ▾
        </span>
      </button>

      <nav className="nav" aria-label="Screens">
        <button
          type="button"
          className={`nav-item ${screen === "dashboard" ? "nav-item--active" : ""}`}
          aria-current={screen === "dashboard" ? "page" : undefined}
          onClick={() => onNavigate("dashboard")}
        >
          <IconGrid />
          Dashboard
        </button>
        <button
          type="button"
          className={`nav-item ${screen === "services" ? "nav-item--active" : ""}`}
          aria-current={screen === "services" ? "page" : undefined}
          onClick={() => onNavigate("services")}
        >
          <IconLayers />
          Services
        </button>
        <button
          type="button"
          className={`nav-item ${screen === "replicas" ? "nav-item--active" : ""}`}
          aria-current={screen === "replicas" ? "page" : undefined}
          onClick={() => onNavigate("replicas")}
        >
          <IconTable />
          Replicas
        </button>
      </nav>

      <div className="sidebar__section">
        <p className="sidebar__section-label">Services</p>
        {services.length === 0 ? (
          <p className="sidebar__empty">No services yet</p>
        ) : (
          services.map((service, index) => (
            <button
              key={service.name}
              type="button"
              className={`folder-item ${index === selectedIndex && screen === "replicas" ? "folder-item--active" : ""}`}
              onClick={() => {
                onSelectService(index);
                onNavigate("replicas");
              }}
            >
              <span
                className={`folder-item__tick folder-item__tick--${serviceBorderStatus(service)}`}
                aria-hidden="true"
              />
              <span className="folder-item__name">{service.name}</span>
            </button>
          ))
        )}
      </div>

      <div className="sidebar__footer">
        <div className="sidebar__footer-mark">
          <IconSignal />
        </div>
        <h2>
          {brokerConnected
            ? "MQTT connected"
            : apiReachable
              ? "API connected"
              : "MQTT reconnecting"}
        </h2>
        <p>
          {isRefreshing ? "Refreshing live snapshot." : "Live snapshot every 5s."}
          {updatedLabel ? ` Bridge ${updatedLabel}.` : ""}
        </p>
        <button type="button" className="pill-btn" style={{ width: "100%" }} disabled>
          {brokerConnected
            ? "Broker online"
            : apiReachable
              ? "Orchestrator online"
              : "Waiting for broker"}
        </button>
      </div>
    </aside>
  );
}
