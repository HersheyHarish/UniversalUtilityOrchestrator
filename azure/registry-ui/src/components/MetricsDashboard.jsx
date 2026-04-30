import React, { useEffect, useState } from "react";
import { observability } from "../api/client.js";
import { Spinner, Alert } from "./Primitives.jsx";
import { IcRefresh } from "./Icons.jsx";

const WINDOW_OPTS = [
  { label: "1 h",   value: 1 },
  { label: "6 h",   value: 6 },
  { label: "24 h",  value: 24 },
  { label: "7 d",   value: 168 },
  { label: "30 d",  value: 720 },
];

function StatCard({ value, label, sub, color }) {
  return (
    <div className="stat-card" style={{ borderTop: `3px solid ${color}` }}>
      <div style={{ fontSize: 28, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function MiniBar({ pct, color }) {
  return (
    <div style={{ flex: 1, height: 6, background: "var(--border)", borderRadius: 3 }}>
      <div style={{ width: `${Math.max(pct, 0)}%`, height: "100%",
        background: color, borderRadius: 3, transition: "width 0.4s" }} />
    </div>
  );
}

function TrendChart({ buckets }) {
  if (!buckets || buckets.length === 0) {
    return <div style={{ height: 80, display: "flex", alignItems: "center",
      justifyContent: "center", color: "var(--text-muted)", fontSize: 12 }}>No data</div>;
  }

  const maxTotal = Math.max(...buckets.map(b => b.total), 1);
  const chartH   = 80;
  const barW     = Math.max(Math.floor(560 / buckets.length) - 2, 2);

  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 2,
      height: chartH, padding: "4px 0" }}>
      {buckets.map((b, i) => {
        const h = Math.max((b.total / maxTotal) * (chartH - 16), 2);
        const failH = b.failed > 0
          ? Math.max((b.failed / b.total) * h, 2)
          : 0;
        const key = b.bucket_start || i;
        return (
          <div key={key} style={{ display: "flex", flexDirection: "column",
            alignItems: "center", flex: 1, gap: 1 }}
            title={`${b.bucket_start?.slice(11,16) || ""}: ${b.total} total, ${b.failed} failed`}>
            {failH > 0 && (
              <div style={{ width: "100%", height: failH, background: "#ef4444",
                borderRadius: "2px 2px 0 0", opacity: 0.8 }} />
            )}
            <div style={{ width: "100%", height: h - failH,
              background: "#22c55e", borderRadius: failH > 0 ? 0 : "2px 2px 0 0",
              opacity: 0.75 }} />
          </div>
        );
      })}
    </div>
  );
}

export default function MetricsDashboard() {
  const [metrics,   setMetrics]   = useState(null);
  const [agents,    setAgents]    = useState([]);
  const [buckets,   setBuckets]   = useState([]);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState("");
  const [hours,     setHours]     = useState(24);

  const load = async () => {
    setLoading(true); setError("");
    try {
      const [m, a, t] = await Promise.all([
        observability.metrics(hours),
        observability.agentMetrics(hours),
        observability.timeseries(hours, hours > 72 ? 6 : 1),
      ]);
      setMetrics(m);
      setAgents(a.agents || []);
      setBuckets(t.buckets || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [hours]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <div className="page-header">
        <div>
          <div className="page-title">Metrics</div>
          <div className="page-desc">System-wide observability and per-agent performance</div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <div className="filter-chips">
            {WINDOW_OPTS.map(o => (
              <span key={o.value} className={`chip ${hours === o.value ? "selected" : ""}`}
                onClick={() => setHours(o.value)}>{o.label}</span>
            ))}
          </div>
          <button className="btn btn-secondary" onClick={load} disabled={loading}>
            <IcRefresh size={14} /> Refresh
          </button>
        </div>
      </div>

      {error && <Alert type="error" onClose={() => setError("")}>{error}</Alert>}

      {loading
        ? <div style={{ display: "flex", justifyContent: "center", padding: 60 }}><Spinner large /></div>
        : (
        <>
          {/* Summary stat cards */}
          <div className="grid-4">
            <StatCard value={metrics?.total ?? 0} label="Total requests"
              sub={`Last ${hours}h`} color="#6366f1" />
            <StatCard value={`${metrics?.success_rate ?? 0}%`} label="Success rate"
              sub={`${metrics?.completed ?? 0} completed`} color="#22c55e" />
            <StatCard value={metrics?.avg_latency_ms ? `${(metrics.avg_latency_ms/1000).toFixed(1)}s` : "—"}
              label="Avg latency" sub={`p95: ${metrics?.p95_latency_ms ? (metrics.p95_latency_ms/1000).toFixed(1)+"s" : "—"}`}
              color="#f59e0b" />
            <StatCard value={metrics?.total_agent_invocations ?? 0}
              label="Agent invocations" sub={`${metrics?.failed ?? 0} failed traces`}
              color="#ef4444" />
          </div>

          {/* Trend chart */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">Request volume</span>
              <div style={{ display: "flex", gap: 12, fontSize: 11 }}>
                <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: "#22c55e", flexShrink: 0 }} />
                  completed
                </span>
                <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: "#ef4444", flexShrink: 0 }} />
                  failed
                </span>
              </div>
            </div>
            <div className="card-body">
              <TrendChart buckets={buckets} />
              {buckets.length > 0 && (
                <div style={{ display: "flex", justifyContent: "space-between",
                  fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
                  <span>{buckets[0]?.bucket_start?.slice(0,16).replace("T", " ")}</span>
                  <span>{buckets[buckets.length-1]?.bucket_start?.slice(0,16).replace("T", " ")}</span>
                </div>
              )}
            </div>
          </div>

          {/* Per-agent table */}
          {agents.length > 0 && (
            <div className="card">
              <div className="card-header">
                <span className="card-title">Per-agent performance</span>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Agent</th>
                      <th>Invocations</th>
                      <th>Success rate</th>
                      <th>Avg latency</th>
                      <th>p95 latency</th>
                      <th>Errors</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.map(a => (
                      <tr key={a.agent_name}>
                        <td style={{ fontWeight: 500 }}>{a.agent_name}</td>
                        <td>{a.invocations}</td>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <MiniBar
                              pct={a.success_rate}
                              color={a.success_rate > 90 ? "#22c55e" : a.success_rate > 70 ? "#f59e0b" : "#ef4444"}
                            />
                            <span style={{ fontSize: 12, minWidth: 40, textAlign: "right",
                              color: a.success_rate > 90 ? "#15803d" : a.success_rate > 70 ? "#92400e" : "#991b1b",
                              fontWeight: 600 }}>
                              {a.success_rate}%
                            </span>
                          </div>
                        </td>
                        <td style={{ fontSize: 13 }}>
                          {a.avg_latency_ms >= 1000
                            ? `${(a.avg_latency_ms/1000).toFixed(1)}s`
                            : `${a.avg_latency_ms}ms`}
                        </td>
                        <td style={{ fontSize: 13 }}>
                          {a.p95_latency_ms >= 1000
                            ? `${(a.p95_latency_ms/1000).toFixed(1)}s`
                            : `${a.p95_latency_ms}ms`}
                        </td>
                        <td>
                          {a.failed > 0
                            ? <span style={{ fontSize: 12, color: "#991b1b",
                                background: "#fee2e2", padding: "1px 8px",
                                borderRadius: 99 }}>
                                {a.failed} failed
                              </span>
                            : <span style={{ fontSize: 12, color: "#15803d" }}>0</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
