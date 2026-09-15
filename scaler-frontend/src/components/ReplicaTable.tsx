import type { ServiceStatus } from "../types/status";
import { formatBytes, formatCpu } from "../lib/metrics";

interface ReplicaTableProps {
  service: ServiceStatus;
}

export function ReplicaTable({ service }: ReplicaTableProps) {
  return (
    <section
      className="panel replica-table"
      aria-label={`${service.name} replicas`}
    >
      <div className="replica-table__head">
        <h2>Replicas · {service.name}</h2>
        <p>{service.replicas.length} containers</p>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Index</th>
              <th>Name</th>
              <th>ID</th>
              <th>Status</th>
              <th>CPU</th>
              <th>Memory</th>
              <th>Net RX</th>
              <th>Net TX</th>
            </tr>
          </thead>
          <tbody>
            {service.replicas.length === 0 ? (
              <tr>
                <td colSpan={8} className="table-empty">
                  No replicas reported
                </td>
              </tr>
            ) : (
              service.replicas.map((replica) => (
                <tr key={replica.id}>
                  <td>{replica.index}</td>
                  <td>{replica.name}</td>
                  <td>
                    <code>{replica.id}</code>
                  </td>
                  <td>
                    <span
                      className={`pill ${
                        replica.status === "running"
                          ? "pill--ok"
                          : "pill--bad"
                      }`}
                    >
                      {replica.status}
                    </span>
                  </td>
                  <td>{formatCpu(replica.cpu_percent)}</td>
                  <td>{formatBytes(replica.memory_bytes)}</td>
                  <td>{formatBytes(replica.net_rx_bytes)}</td>
                  <td>{formatBytes(replica.net_tx_bytes)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
