import { ServiceGrid } from "../components/ServiceGrid";
import type { ServiceStatus } from "../types/status";

interface ServicesScreenProps {
  services: ServiceStatus[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  commandsEnabled: boolean;
  waitingMessage: string;
}

export function ServicesScreen({
  services,
  selectedIndex,
  onSelect,
  commandsEnabled,
  waitingMessage,
}: ServicesScreenProps) {
  if (services.length === 0) {
    return <p className="load-state load-state--inline">{waitingMessage}</p>;
  }

  return (
    <section className="panel" aria-label="Services">
      <h2>Your services</h2>
      <ServiceGrid
        services={services}
        selectedIndex={selectedIndex}
        onSelect={onSelect}
        commandsEnabled={commandsEnabled}
      />
    </section>
  );
}
