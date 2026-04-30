import React, { useMemo } from "react";

const ROW_H  = 36;
const LABEL_W = 140;
const PADDING = 10;

const STATUS_COLOR = {
  completed: "#22c55e",
  failed:    "#ef4444",
  running:   "#6366f1",
  skipped:   "#94a3b8",
};

function msLabel(ms) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

export default function TimelineView({ steps, traceStartedAt, onSelectStep, selectedStepId }) {
  const data = useMemo(() => {
    if (!steps || steps.length === 0) return null;

    const t0 = traceStartedAt
      ? new Date(traceStartedAt).getTime()
      : Math.min(...steps
          .filter(s => s.started_at)
          .map(s => new Date(s.started_at).getTime()));

    const maxEnd = Math.max(...steps.map(s => {
      const start   = s.started_at ? new Date(s.started_at).getTime() : t0;
      const latency = s.latency_ms || 0;
      return start - t0 + latency;
    }));

    const totalMs = Math.max(maxEnd, 100);

    return { t0, totalMs };
  }, [steps, traceStartedAt]);

  if (!data || !steps?.length) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontSize: 14 }}>
        No timeline data available
      </div>
    );
  }

  const { t0, totalMs } = data;
  const svgW      = 700;
  const chartW    = svgW - LABEL_W - PADDING * 2;
  const svgH      = steps.length * ROW_H + 40 + 30; // +30 for axis

  // Time axis ticks (4-5 ticks)
  const tickCount  = 5;
  const tickMs     = totalMs / tickCount;

  function xOf(ms) {
    return LABEL_W + PADDING + (ms / totalMs) * chartW;
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <svg width="100%" viewBox={`0 0 ${svgW} ${svgH}`}
        style={{ minWidth: svgW, display: "block" }}>

        {/* Gridlines */}
        {Array.from({ length: tickCount + 1 }, (_, i) => {
          const ms = i * tickMs;
          const x  = xOf(ms);
          return (
            <g key={i}>
              <line x1={x} y1={30} x2={x} y2={svgH - 30}
                stroke="var(--color-border-tertiary)" strokeWidth="0.5" />
              <text x={x} y={20} fontSize={10} textAnchor="middle"
                fill="var(--color-text-secondary)">
                {msLabel(Math.round(ms))}
              </text>
            </g>
          );
        })}

        {/* Step rows */}
        {steps.map((s, i) => {
          const startMs = s.started_at
            ? new Date(s.started_at).getTime() - t0
            : 0;
          const dur     = s.latency_ms || 0;
          const barX    = xOf(startMs);
          const barW    = Math.max((dur / totalMs) * chartW, dur > 0 ? 4 : 2);
          const y       = 30 + i * ROW_H;
          const color   = STATUS_COLOR[s.status] || "#94a3b8";
          const isSelected = selectedStepId === s.step_id;

          const labelTrunc = (s.agent_name || "").length > 16
            ? s.agent_name.slice(0, 15) + "…"
            : s.agent_name;

          return (
            <g key={s.step_id} style={{ cursor: "pointer" }}
              onClick={() => onSelectStep?.(s)}>
              {/* Row background on hover */}
              <rect x={0} y={y} width={svgW} height={ROW_H - 2} rx={0}
                fill={isSelected ? "#f0f4ff" : "transparent"}
                opacity={0.6} />

              {/* Step label */}
              <text x={LABEL_W - 8} y={y + ROW_H / 2} fontSize={11}
                textAnchor="end" dominantBaseline="middle"
                fill="var(--color-text-secondary)" fontWeight={isSelected ? "600" : "400"}>
                {`${s.step_id}. ${labelTrunc}`}
              </text>

              {/* Status dot */}
              <circle cx={LABEL_W - PADDING - 4} cy={y + ROW_H / 2} r={3.5} fill={color} />

              {/* Bar */}
              <rect x={barX} y={y + 6} width={barW} height={ROW_H - 14} rx={4}
                fill={color} opacity={isSelected ? 1 : 0.75}
                stroke={isSelected ? "#6366f1" : "none"} strokeWidth={1.5} />

              {/* Latency label inside bar (if wide enough) */}
              {barW > 40 && dur > 0 && (
                <text x={barX + barW / 2} y={y + ROW_H / 2} fontSize={9}
                  textAnchor="middle" dominantBaseline="middle" fill="#fff" fontWeight="600">
                  {msLabel(dur)}
                </text>
              )}

              {/* Latency label outside bar */}
              {barW <= 40 && dur > 0 && (
                <text x={barX + barW + 4} y={y + ROW_H / 2} fontSize={9}
                  textAnchor="start" dominantBaseline="middle"
                  fill="var(--color-text-muted)">
                  {msLabel(dur)}
                </text>
              )}

              {/* Error marker */}
              {s.status === "failed" && (
                <text x={barX + barW + (barW <= 40 ? 36 : 4)} y={y + ROW_H / 2}
                  fontSize={10} fill="#ef4444" dominantBaseline="middle">✕</text>
              )}
            </g>
          );
        })}

        {/* Axis baseline */}
        <line x1={LABEL_W} y1={svgH - 28} x2={svgW - PADDING} y2={svgH - 28}
          stroke="var(--color-border-secondary)" strokeWidth="1" />
        <text x={LABEL_W} y={svgH - 14} fontSize={10}
          fill="var(--color-text-secondary)">0</text>
        <text x={svgW - PADDING} y={svgH - 14} fontSize={10}
          textAnchor="end" fill="var(--color-text-secondary)">
          {msLabel(totalMs)}
        </text>
      </svg>

      <div style={{ display: "flex", gap: 16, padding: "6px 4px",
        fontSize: 11, color: "var(--text-muted)" }}>
        {Object.entries(STATUS_COLOR).map(([s, c]) => (
          <div key={s} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2,
              background: c, flexShrink: 0 }} />
            {s}
          </div>
        ))}
        <span style={{ marginLeft: "auto" }}>Click a bar to inspect</span>
      </div>
    </div>
  );
}
