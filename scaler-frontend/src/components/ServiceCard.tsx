import { useState } from "react";
import type { ServiceStatus } from "../types/status";
import { deriveServiceFields } from "../types/status";
import { publishDeviceCommand } from "../api/publishCmd";
import { formatCpu, serviceBorderStatus } from "../lib/metrics";

interface ServiceCardProps {
  service: ServiceStatus;
  selected: boolean;
  onSelect: () => void;
  commandsEnabled?: boolean;
}

export function ServiceCard({
  service,
  selected,
  onSelect,
  commandsEnabled = true,
}: ServiceCardProps) {
  const derived = deriveServiceFields(service);
  const borderStatus = serviceBorderStatus(service);
  const [pending, setPending] = useState<"start" | "stop" | null>(null);
  const [cmdError, setCmdError] = useState<string | null>(null);

  const stopped =
    service.desired_replicas === 0 && service.actual_replicas === 0;
  const busy = pending !== null;

  const runCommand = async (action: "start" | "stop") => {
    if (!commandsEnabled || busy) return;
    setPending(action);
    setCmdError(null);
    try {
      await publishDeviceCommand({ action, service: service.name });
    } catch (err) {
      setCmdError(err instanceof Error ? err.message : "Command failed");
    } finally {
      setPending(null);
    }
  };

  return (
    <article
      className={["doc-card", selected ? "doc-card--selected" : ""]
        .filter(Boolean)
        .join(" ")}
      data-status={borderStatus}
      aria-selected={selected}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      role="button"
      tabIndex={0}
    >
      <div className="doc-card__top">
        <div className="doc-card__folder" aria-hidden="true">
          <span className={`status-dot status-dot--${borderStatus}`} />
        </div>
      </div>

      <div className="doc-card__title">
        <h2>{service.name}</h2>
      </div>

      <p className="doc-card__copy">
        {service.actual_replicas}/{service.desired_replicas} replicas ·{" "}
        {formatCpu(service.avg_cpu)} CPU · {derived.memory_mb.toFixed(0)} MiB
      </p>

      {derived.cooldown_active ? (
        <span className="chip">
          cooldown {Math.ceil(service.cooldown_remaining_seconds)}s
        </span>
      ) : null}

      {cmdError ? <p className="doc-card__error">{cmdError}</p> : null}

      <div
        className="doc-card__actions"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          className="pill-btn"
          disabled={!commandsEnabled || busy || !stopped}
          title={`Start ${service.name}`}
          onClick={() => void runCommand("start")}
        >
          {pending === "start" ? "…" : "Start"}
        </button>
        <button
          type="button"
          className="pill-btn"
          disabled={!commandsEnabled || busy || stopped}
          title={`Stop ${service.name}`}
          onClick={() => void runCommand("stop")}
        >
          {pending === "stop" ? "…" : "Stop"}
        </button>
      </div>
    </article>
  );
}
