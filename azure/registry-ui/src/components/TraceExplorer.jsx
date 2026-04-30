import React, { useEffect, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { traces } from "../api/client.js";
import { Spinner, Alert, EmptyState } from "./Primitives.jsx";
import { IcRefresh, IcSearch, IcFilter, IcChevronRight } from "./Icons.jsx";

const STATUS_OPTS = ["all", "completed", "failed", "running"];
const WINDOW_OPTS = [
  { label: "Last 1 h", value: 1 },
  { label: "Last 6 h", value: 6 },
  { label: "Last 24 h", value: 24 },
  { label: "Last 7 d", value: 168 },
  { label: "Last 30 d", value: 720 },
];

const STATUS_STYLE = {
  completed: { bg: "#dcfce7", color: "#15803d", dot: "#22c55e" },
  failed: { bg: "#fee2e2", color: "#991b1b", dot: "#ef4444" },
  running: { bg: "#e0e7ff", color: "#3730a3", dot: "#6366f1" },
};

function StatusPill({ status }) {
  const s = STATUS_STYLE[status] || { bg: "#f1f5f9", color: "#334155", dot: "#94a3b8" };
  return (
    <span style={{
      background: s.bg, color: s.color, padding: "2px 10px",
      borderRadius: 99, fontSize: 12, fontWeight: 500, display: "inline-flex",
      alignItems: "center", gap: 5, whiteSpace: "nowrap"
    }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: s.dot }} />
      {status}
    </span>
  );
}

function LatencyBar({ ms, maxMs }) {
  if (!ms) return <span style={{ color: "var(--text-muted)", fontSize: 12 }}>—</span>;
  const pct = Math.min((ms / maxMs) * 100, 100);
  const color = ms > 5000 ? "#ef4444" : ms > 2000 ? "#f59e0b" : "#22c55e";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 100 }}>
      <div style={{ flex: 1, height: 4, background: "var(--border)", borderRadius: 2 }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 12, color: "var(--text-secondary)", minWidth: 48, textAlign: "right" }}>
        {ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`}
      </span>
    </div>
  );
}

export default function TraceExplorer() {
  const navigate = useNavigate();
  const [sp, setSP] = useSearchParams();

  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState(sp.get("q") || "");
  const [status, setStatus] = useState(sp.get("status") || "all");
  const [agent, setAgent] = useState(sp.get("agent") || "");
  const [sinceHours, setSinceHours] = useState(Number(sp.get("since") || 24));

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const res = await traces.list({
        status: status !== "all" ? status : undefined,
        agent: agent.trim() || undefined,
        since_hours: sinceHours,
        limit: 100,
      });
      setList(res.traces || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [status, agent, sinceHours]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const p = {};
    if (q) p.q = q;
    if (status !== "all") p.status = status;
    if (agent) p.agent = agent;
    if (sinceHours !== 24) p.since = String(sinceHours);
    setSP(p, { replace: true });
  }, [q, status, agent, sinceHours, setSP]);

  const filtered = q.trim()
    ? list.filter(t =>
      (t.user_message || "").toLowerCase().includes(q.toLowerCase()) ||
      (t.customer_id || "").toLowerCase().includes(q.toLowerCase()) ||
      (t.user_intent || "").toLowerCase().includes(q.toLowerCase())
    )
    : list;

  const maxMs = Math.max(...filtered.map(t => t.total_latency_ms || 0), 1);

  const agentNames = [...new Set(list.flatMap(t => []))];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div className="page-header">
        <div>
          <div className="page-title">Trace explorer</div>
          <div className="page-desc">
            {filtered.length} trace{filtered.length !== 1 ? "s" : ""} · end-to-end execution history
          </div>
        </div>
        <button className="btn btn-secondary" onClick={load}>
          <IcRefresh size={14} /> Refresh
        </button>
      </div>

      {error && <Alert type="error" onClose={() => setError("")}>{error}</Alert>}

      {/* Filters */}
      <div className="card">
        <div className="card-body" style={{
          padding: "14px 16px", display: "flex",
          gap: 16, flexWrap: "wrap", alignItems: "center"
        }}>
          <div className="search-bar" style={{ maxWidth: 340 }}>
            <IcSearch size={15} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
            <input placeholder="Search message, customer ID, intent…"
              value={q} onChange={e => setQ(e.target.value)} />
            {q && <button style={{
              background: "none", border: "none", cursor: "pointer",
              color: "var(--text-muted)", fontSize: 18
            }} onClick={() => setQ("")}>×</button>}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <IcFilter size={13} style={{ color: "var(--text-muted)" }} />
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Status:</span>
            <div className="filter-chips">
              {STATUS_OPTS.map(s => (
                <span key={s} className={`chip ${status === s ? "selected" : ""}`}
                  onClick={() => setStatus(s)}>
                  {s === "all" ? "All" : s}
                </span>
              ))}
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Window:</span>
            <select className="form-control" value={sinceHours}
              onChange={e => setSinceHours(Number(e.target.value))}
              style={{ width: "auto", fontSize: 13, padding: "5px 10px" }}>
              {WINDOW_OPTS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Agent:</span>
            <input className="form-control" value={agent}
              onChange={e => setAgent(e.target.value)}
              placeholder="filter by agent name"
              style={{ width: 180, fontSize: 13, padding: "5px 10px" }} />
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="card">
        {loading
          ? <div style={{ display: "flex", justifyContent: "center", padding: 48 }}>
            <Spinner large />
          </div>
          : filtered.length === 0
            ? <EmptyState icon="🔍" title="No traces found"
              desc="Traces appear after the orchestrator processes requests. Check your time window or filters." />
            : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Request</th>
                      <th>Status</th>
                      <th>Agents</th>
                      <th>Latency</th>
                      <th>Started</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map(t => (
                      <tr key={t.id} style={{ cursor: "pointer" }}
                        onClick={() => navigate(`/traces/${t.id}`)}>
                        <td>
                          <div style={{
                            fontWeight: 500, fontSize: 14, maxWidth: 340,
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"
                          }}>
                            {t.user_message || "(no message)"}
                          </div>
                          <div style={{ display: "flex", gap: 8, marginTop: 3 }}>
                            {t.customer_id && (
                              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                                {t.customer_id}
                              </span>
                            )}
                            {t.user_intent && (
                              <span style={{
                                fontSize: 11, color: "var(--text-secondary)",
                                maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis",
                                whiteSpace: "nowrap"
                              }}>
                                Intent: {t.user_intent}
                              </span>
                            )}
                          </div>
                        </td>
                        <td><StatusPill status={t.status} /></td>
                        <td>
                          <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>
                            {t.agents_invoked || 0}
                            <span style={{ color: "var(--text-muted)", marginLeft: 4 }}>
                              / {t.step_count || 0} steps
                            </span>
                          </span>
                        </td>
                        <td><LatencyBar ms={t.total_latency_ms} maxMs={maxMs} /></td>
                        <td style={{ fontSize: 12, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                          {t.started_at ? new Date(t.started_at).toLocaleString() : "—"}
                        </td>
                        <td>
                          <IcChevronRight size={14} style={{ color: "var(--text-muted)" }} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
      </div>
    </div>
  );
}
