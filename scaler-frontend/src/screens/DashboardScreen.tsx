import { CpuChart } from "../components/CpuChart";
import { DeviceHeader } from "../components/DeviceHeader";
import { FleetSummary } from "../components/FleetSummary";
import type { DeviceDiscovery, DeviceOnlineStatus, DeviceStatus } from "../types/status";

interface DashboardScreenProps {
  deviceStatus: DeviceOnlineStatus;
  discovery: DeviceDiscovery | null;
  status: DeviceStatus | null;
  totals: {
    serviceCount: number;
    desired: number;
    actual: number;
    healthy: number;
  };
  waitingMessage: string;
}

export function DashboardScreen({
  deviceStatus,
  discovery,
  status,
  totals,
  waitingMessage,
}: DashboardScreenProps) {
  return (
    <>
      <DeviceHeader deviceStatus={deviceStatus} discovery={discovery} />
      {status ? (
        <>
          <FleetSummary
            serviceCount={totals.serviceCount}
            desired={totals.desired}
            actual={totals.actual}
            healthy={totals.healthy}
          />
          <CpuChart services={status.services} />
        </>
      ) : (
        <p className="load-state load-state--inline">{waitingMessage}</p>
      )}
    </>
  );
}
