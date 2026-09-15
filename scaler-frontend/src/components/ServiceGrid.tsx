import type { ServiceStatus } from "../types/status";
import { ServiceCard } from "./ServiceCard";

interface ServiceGridProps {
  services: ServiceStatus[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  commandsEnabled?: boolean;
}

export function ServiceGrid({
  services,
  selectedIndex,
  onSelect,
  commandsEnabled = true,
}: ServiceGridProps) {
  return (
    <div className="service-grid">
      {services.map((service, index) => (
        <ServiceCard
          key={service.name}
          service={service}
          selected={index === selectedIndex}
          onSelect={() => onSelect(index)}
          commandsEnabled={commandsEnabled}
        />
      ))}
    </div>
  );
}
