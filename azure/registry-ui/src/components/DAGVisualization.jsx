import React, { useMemo, useState, useRef, useEffect } from "react";

const NODE_W   = 160;
const NODE_H   = 60;
const H_GAP    = 90;   // horizontal gap between layers
const V_GAP    = 24;   // vertical gap between nodes in same layer

const STATUS_COLORS = {
  completed: { fill: "#dcfce7", stroke: "#16a34a", text: "#15803d", dot: "#22c55e" },
  failed:    { fill: "#fee2e2", stroke: "#dc2626", text: "#991b1b", dot: "#ef4444" },
  running:   { fill: "#e0e7ff", stroke: "#6366f1", text: "#3730a3", dot: "#6366f1" },
  skipped:   { fill: "#f1f5f9", stroke: "#94a3b8", text: "#64748b", dot: "#94a3b8" },
};

function msLabel(ms) {
  if (!ms) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

// ── Layout algorithm ──────────────────────────────────────────────────────────
function computeLayout(steps) {
  if (!steps || steps.length === 0) return { nodes: [], edges: [] };

  const byId = {};
  steps.forEach(s => { byId[s.step_id] = s; });

  // Assign layer = max(dep layers) + 1
  const layer = {};
  const visited = new Set();

  function assignLayer(id) {
    if (id in layer) return layer[id];
    if (visited.has(id)) return 0; // cycle guard
    visited.add(id);
    const s = byId[id];
    if (!s) return 0;
    const deps = s.depends_on || [];
    const maxDep = deps.length > 0 ? Math.max(...deps.map(assignLayer)) : -1;
    layer[id] = maxDep + 1;
    return layer[id];
  }
  steps.forEach(s => assignLayer(s.step_id));

  // Group by layer
  const groups = {};
  steps.forEach(s => {
    const l = layer[s.step_id];
    if (!groups[l]) groups[l] = [];
    groups[l].push(s.step_id);
  });

  const maxLayer = Math.max(...Object.keys(groups).map(Number));
  const totalWidth  = (maxLayer + 1) * (NODE_W + H_GAP) + 40;

  const positions = {};
  Object.entries(groups).forEach(([l, ids]) => {
    const layerNum = Number(l);
    const totalH   = ids.length * NODE_H + (ids.length - 1) * V_GAP;
    ids.forEach((id, i) => {
      positions[id] = {
        x: 20 + layerNum * (NODE_W + H_GAP),
        y: 20 + i * (NODE_H + V_GAP),
      };
    });
  });

  const maxNodesInLayer = Math.max(...Object.values(groups).map(arr => arr.length));
  const totalHeight = maxNodesInLayer * NODE_H + (maxNodesInLayer - 1) * V_GAP + 40;

  const nodes = steps.map(s => ({
    ...s,
    x: positions[s.step_id]?.x || 0,
    y: positions[s.step_id]?.y || 0,
  }));

  const edges = [];
  steps.forEach(s => {
    (s.depends_on || []).forEach(depId => {
      edges.push({ fromId: depId, toId: s.step_id });
    });
  });

  return { nodes, edges, totalWidth, totalHeight };
}

function EdgePath({ from, to }) {
  const x1 = from.x + NODE_W;
  const y1 = from.y + NODE_H / 2;
  const x2 = to.x;
  const y2 = to.y + NODE_H / 2;
  const cx  = (x1 + x2) / 2;
  const d   = `M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`;
  return (
    <path d={d} fill="none" stroke="#94a3b8" strokeWidth="1.5"
      markerEnd="url(#dag-arrow)" />
  );
}

function DAGNode({ node, selected, onClick }) {
  const c    = STATUS_COLORS[node.status] || STATUS_COLORS.skipped;
  const lms  = msLabel(node.latency_ms);
  const name = node.agent_name.length > 16
    ? node.agent_name.slice(0, 15) + "…"
    : node.agent_name;
  const task = (node.task || "").slice(0, 28) + ((node.task || "").length > 28 ? "…" : "");

  return (
    <g style={{ cursor: "pointer" }} onClick={() => onClick(node)}>
      <rect x={node.x} y={node.y} width={NODE_W} height={NODE_H} rx={8}
        fill={c.fill}
        stroke={selected ? "#6366f1" : c.stroke}
        strokeWidth={selected ? 2 : 1} />
      {/* Status dot */}
      <circle cx={node.x + 14} cy={node.y + 14} r={5} fill={c.dot} />
      {/* Step number */}
      <text x={node.x + 26} y={node.y + 19}
        fontSize={10} fill={c.text} fontWeight="600" textAnchor="start"
        dominantBaseline="middle">
        {node.step_id}
      </text>
      {/* Agent name */}
      <text x={node.x + NODE_W / 2} y={node.y + 28}
        fontSize={13} fill={c.text} fontWeight="600"
        textAnchor="middle" dominantBaseline="middle">
        {name}
      </text>
      {/* Task snippet */}
      <text x={node.x + NODE_W / 2} y={node.y + 44}
        fontSize={10} fill={c.text} textAnchor="middle" dominantBaseline="middle"
        opacity={0.75}>
        {task}
      </text>
      {/* Latency badge */}
      {lms && (
        <g>
          <rect x={node.x + NODE_W - 42} y={node.y + 4} width={38} height={16} rx={6}
            fill={c.stroke} opacity={0.15} />
          <text x={node.x + NODE_W - 23} y={node.y + 12}
            fontSize={9} fill={c.text} fontWeight="600"
            textAnchor="middle" dominantBaseline="middle">
            {lms}
          </text>
        </g>
      )}
      {/* Error indicator */}
      {node.status === "failed" && (
        <text x={node.x + 8} y={node.y + NODE_H - 8}
          fontSize={10} fill="#dc2626">✕</text>
      )}
    </g>
  );
}

export default function DAGVisualization({ steps, selectedStepId, onSelectStep }) {
  const { nodes, edges, totalWidth, totalHeight } = useMemo(
    () => computeLayout(steps || []),
    [steps]
  );

  const byId = {};
  nodes.forEach(n => { byId[n.step_id] = n; });

  if (!nodes.length) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontSize: 14 }}>
        No steps to display
      </div>
    );
  }

  return (
    <div style={{ overflowX: "auto", overflowY: "visible" }}>
      <svg
        width={totalWidth}
        height={totalHeight}
        style={{ minWidth: "100%", display: "block" }}
      >
        <defs>
          <marker id="dag-arrow" viewBox="0 0 10 10" refX="8" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M2 1L8 5L2 9" fill="none" stroke="#94a3b8"
              strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </marker>
        </defs>

        {/* Edges first so nodes render on top */}
        {edges.map((e, i) => {
          const from = byId[e.fromId];
          const to   = byId[e.toId];
          if (!from || !to) return null;
          return <EdgePath key={i} from={from} to={to} />;
        })}

        {/* Nodes */}
        {nodes.map(n => (
          <DAGNode key={n.step_id} node={n}
            selected={selectedStepId === n.step_id}
            onClick={onSelectStep} />
        ))}
      </svg>

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, padding: "10px 4px 4px",
        fontSize: 11, color: "var(--text-muted)" }}>
        {Object.entries(STATUS_COLORS).map(([s, c]) => (
          <div key={s} style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%",
              background: c.dot, flexShrink: 0 }} />
            {s}
          </div>
        ))}
        <span style={{ marginLeft: "auto" }}>Click a node to inspect</span>
      </div>
    </div>
  );
}
