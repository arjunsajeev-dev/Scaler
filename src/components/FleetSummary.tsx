interface FleetSummaryProps {
  serviceCount: number;
  desired: number;
  actual: number;
  healthy: number;
}

export function FleetSummary({
  serviceCount,
  desired,
  actual,
  healthy,
}: FleetSummaryProps) {
  const items = [
    { label: "Services", value: serviceCount },
    { label: "Desired", value: desired },
    { label: "Actual", value: actual },
    { label: "Healthy", value: healthy },
  ];

  return (
    <section className="fleet-summary" aria-label="Fleet summary">
      {items.map((item) => (
        <div key={item.label} className="fleet-summary__stat">
          <span className="fleet-summary__label">{item.label}</span>
          <span className="fleet-summary__value">{item.value}</span>
        </div>
      ))}
    </section>
  );
}
