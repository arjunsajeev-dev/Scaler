import { ReplicaTable } from "../components/ReplicaTable";
import type { ServiceStatus } from "../types/status";

interface ReplicasScreenProps {
  service: ServiceStatus | null;
  waitingMessage: string;
}

export function ReplicasScreen({ service, waitingMessage }: ReplicasScreenProps) {
  if (!service) {
    return <p className="load-state load-state--inline">{waitingMessage}</p>;
  }

  return <ReplicaTable service={service} />;
}
