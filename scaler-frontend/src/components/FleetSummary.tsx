interface FleetSummaryProps {
  serviceCount: number;
  desired: number;
  actual: number;
  healthy: number;
}

function ContainerGlyph() {
  return (
    <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <rect
        x="10"
        y="14"
        width="28"
        height="22"
        rx="3"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path d="M10 22h28M18 14v22M30 14v22" stroke="currentColor" strokeWidth="2" />
      <path d="M16 14 20 8h8l4 6" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

export function FleetSummary({
  serviceCount,
  desired,
  actual,
  healthy,
}: FleetSummaryProps) {
  return (
    <section className="stat-row" aria-label="Fleet summary">
      <div className="stat-tile">
        <span className="stat-tile__label">Actual replicas</span>
        <span className="stat-tile__value">{actual}</span>
      </div>
      <div className="stat-tile stat-tile--icon" title={`Desired ${desired}`}>
        <ContainerGlyph />
        <span>{serviceCount} services</span>
      </div>
      <div className="stat-tile">
        <span className="stat-tile__label">Healthy</span>
        <span className="stat-tile__value">{healthy}</span>
      </div>
    </section>
  );
}
