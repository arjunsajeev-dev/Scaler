import { useState } from "react";
import type { ServiceStatus } from "../types/status";
import { deriveServiceFields } from "../types/status";
import { publishDeviceCommand } from "../api/publishCmd";
import { clampPercent, formatCpu, serviceBorderStatus } from "../lib/metrics";

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
  const cpuWidth = clampPercent(service.avg_cpu);
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
      className={[
        "service-card",
        `service-card--${borderStatus}`,
        selected ? "service-card--selected" : "",
      ]
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
      <div className="service-card__top">
        <div className="service-card__title">
          <span
            className={`status-dot status-dot--pulse status-dot--${borderStatus}`}
            aria-hidden="true"
          />
          <h2>{service.name}</h2>
        </div>
        <div
          className="service-card__actions"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            className={`svc-btn ${stopped ? "svc-btn--start" : "svc-btn--stop"}`}
            disabled={!commandsEnabled || busy}
            title={stopped ? `Start ${service.name}` : `Stop ${service.name}`}
            onClick={() => void runCommand(stopped ? "start" : "stop")}
          >
            {pending ? "…" : stopped ? "Start" : "Stop"}
          </button>
        </div>
      </div>

      {derived.cooldown_active ? (
        <span className="chip chip--cooldown">
          cooldown {Math.ceil(service.cooldown_remaining_seconds)}s
        </span>
      ) : null}

      {cmdError ? <p className="service-card__error">{cmdError}</p> : null}

      <dl className="service-card__replicas">
        <div>
          <dt>Desired</dt>
          <dd>{service.desired_replicas}</dd>
        </div>
        <div>
          <dt>Actual</dt>
          <dd>{service.actual_replicas}</dd>
        </div>
        <div>
          <dt>Healthy</dt>
          <dd>{service.healthy}</dd>
        </div>
        <div>
          <dt>Gap</dt>
          <dd className={derived.scale_gap !== 0 ? "text-warn" : undefined}>
            {derived.scale_gap > 0 ? `+${derived.scale_gap}` : derived.scale_gap}
          </dd>
        </div>
      </dl>

      <div className="meter">
        <div className="meter__label">
          <span>CPU</span>
          <span>{formatCpu(service.avg_cpu)}</span>
        </div>
        <div className="meter__track" aria-hidden="true">
          <div className="meter__fill" style={{ width: `${cpuWidth}%` }} />
        </div>
      </div>

      <div className="service-card__meta">
        <span>{derived.memory_mb.toFixed(0)} MiB avg</span>
        <span>
          hi {service.consecutive_high} · lo {service.consecutive_low}
        </span>
        <span>{(derived.health_ratio * 100).toFixed(0)}% healthy</span>
      </div>
    </article>
  );
}
