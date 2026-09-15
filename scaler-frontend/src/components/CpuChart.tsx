import { deriveServiceFields, type ServiceStatus } from "../types/status";
import { clampPercent } from "../lib/metrics";

interface CpuChartProps {
  services: ServiceStatus[];
}

function polyline(values: number[], x: (i: number) => number, y: (v: number) => number): string {
  if (values.length === 0) return "";
  if (values.length === 1) {
    return `${x(0)},${y(values[0])} ${x(1)},${y(values[0])}`;
  }
  return values.map((value, index) => `${x(index)},${y(value)}`).join(" ");
}

export function CpuChart({ services }: CpuChartProps) {
  const width = 640;
  const height = 220;
  const pad = { top: 12, right: 12, bottom: 28, left: 36 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const cpu = services.map((service) => clampPercent(service.avg_cpu));
  const health = services.map((service) =>
    clampPercent(deriveServiceFields(service).health_ratio * 100),
  );
  const count = Math.max(services.length, 1);
  const maxX = Math.max(count - 1, 1);
  const x = (index: number) => pad.left + (index / maxX) * innerW;
  const y = (value: number) => pad.top + innerH - (value / 100) * innerH;
  const ticks = [0, 25, 50, 75, 100];
  const cpuLine = polyline(cpu, x, y);
  const healthLine = polyline(health, x, y);
  const areaPoints =
    cpu.length === 0
      ? ""
      : `${x(0)},${y(0)} ${cpuLine} ${x(cpu.length <= 1 ? 1 : cpu.length - 1)},${y(0)}`;

  return (
    <section className="panel" aria-label="CPU by service">
      <h2>CPU by service</h2>
      {services.length === 0 ? (
        <p className="chart-empty">No service metrics yet</p>
      ) : (
        <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img">
          <title>Average CPU (solid) and healthy ratio (dashed) per service</title>
          <defs>
            <pattern
              id="cpuHatch"
              patternUnits="userSpaceOnUse"
              width="8"
              height="8"
              patternTransform="rotate(40)"
            >
              <line x1="0" y1="0" x2="0" y2="8" stroke="rgba(255,255,255,0.28)" strokeWidth="1" />
            </pattern>
          </defs>
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                className="chart__grid"
                x1={pad.left}
                x2={width - pad.right}
                y1={y(tick)}
                y2={y(tick)}
              />
              <text className="chart__axis" x={4} y={y(tick) + 3}>
                {tick}
              </text>
            </g>
          ))}
          {areaPoints ? <polygon className="chart__area" points={areaPoints} /> : null}
          <polyline className="chart__line" points={cpuLine} />
          <polyline className="chart__line chart__line--dash" points={healthLine} />
          {services.map((service, index) => (
            <text
              key={service.name}
              className="chart__axis"
              x={x(services.length === 1 ? 0.5 : index)}
              y={height - 6}
              textAnchor="middle"
            >
              {service.name}
            </text>
          ))}
        </svg>
      )}
    </section>
  );
}
