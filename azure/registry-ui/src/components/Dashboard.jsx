import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { registry, agents as agentsApi } from "../api/client.js";
import { Spinner, StatusBadge, HealthDot, Alert, EmptyState } from "./Primitives.jsx";
import { IcAgents, IcHealth, IcZap, IcRefresh, IcChevronRight } from "./Icons.jsx";

function StatCard({ icon, bg, value, label, sub }) {
  return (
    <div className="stat-card">
      <div className="stat-icon" style={{ background: bg }}>{icon}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export default function Dashboard() {
  const navigate          = useNavigate();
  const [stats,  setStats]  = useState(null);
  const [recent, setRecent] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,  setError]   = useState("");

  const load = async () => {
    setLoading(true); setError("");
    try {
      const [s, a] = await Promise.all([registry.stats(), agentsApi.list()]);
      setStats(s);
      setRecent((a.agents || []).slice(0, 6));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (loading) return (
    <div style={{ display: "flex", justifyContent: "center", padding: 60 }}>
      <Spinner large />
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <div className="page-header">
        <div>
          <div className="page-title">Dashboard</div>
          <div className="page-desc">Registry health at a glance</div>
        </div>
        <button className="btn btn-secondary" onClick={load}>
          <IcRefresh size={14} /> Refresh
        </button>
      </div>

      {error && <Alert type="error" onClose={() => setError("")}>{error}</Alert>}

      {/* Stat cards */}
      <div className="grid-4">
        <StatCard icon={<IcAgents size={18} />} bg="#ede9fe"
          value={stats?.total ?? "—"} label="Total agents"
          sub={`${stats?.by_status?.active ?? 0} active`} />
        <StatCard icon={<IcHealth size={18} />} bg="#dcfce7"
          value={stats?.by_status?.active ?? "—"} label="Active"
          sub={`${stats?.by_status?.degraded ?? 0} degraded`} />
        <StatCard icon={<IcZap size={18} />} bg="#e0e7ff"
          value={stats?.total_capabilities ?? "—"} label="Capabilities"
          sub={`${stats?.unique_tags?.length ?? 0} unique tags`} />
        <StatCard icon="💤" bg="#fef3c7"
          value={stats?.by_status?.inactive ?? 0} label="Inactive"
          sub="Soft-deleted agents" />
      </div>

      {/* Utility type breakdown */}
      {stats?.by_utility_type && Object.keys(stats.by_utility_type).length > 0 && (
        <div className="card">
          <div className="card-header"><span className="card-title">By utility type</span></div>
          <div className="card-body">
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              {Object.entries(stats.by_utility_type).map(([type, count]) => (
                <div key={type} style={{ padding: "12px 20px", borderRadius: "var(--radius)",
                  background: "var(--bg-page)", border: "1px solid var(--border)",
                  textAlign: "center", minWidth: 90 }}>
                  <div style={{ fontSize: 24, fontWeight: 700 }}>{count}</div>
                  <div style={{ fontSize: 12, color: "var(--text-secondary)",
                    textTransform: "capitalize" }}>{type}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tags */}
      {stats?.unique_tags?.length > 0 && (
        <div className="card">
          <div className="card-header"><span className="card-title">Tags in registry</span></div>
          <div className="card-body">
            <div className="tag-list">
              {stats.unique_tags.map(t => (
                <span key={t} className="badge badge-tag" style={{ cursor: "pointer" }}
                  onClick={() => navigate(`/agents?tag=${t}`)}>{t}</span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Recent agents */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Recent agents</span>
          <button className="btn btn-ghost btn-sm" onClick={() => navigate("/agents")}>
            View all <IcChevronRight size={13} />
          </button>
        </div>
        {recent.length === 0
          ? <EmptyState icon="🤖" title="No agents yet"
              desc="Register your first agent to get started." />
          : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th><th>Status</th><th>Utility types</th>
                  <th>Health</th><th>Updated</th><th></th>
                </tr>
              </thead>
              <tbody>
                {recent.map(a => (
                  <tr key={a.id} style={{ cursor: "pointer" }}
                    onClick={() => navigate(`/agents/${a.id}`)}>
                    <td>
                      <div style={{ fontWeight: 500 }}>{a.name}</div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{a.version}</div>
                    </td>
                    <td><StatusBadge status={a.status} /></td>
                    <td>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        {(a.utility_types || []).map(t => (
                          <span key={t} className="badge"
                            style={{ background: "#f0fdf4", color: "#166534", padding: "1px 6px", fontSize: 11 }}>
                            {t}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <HealthDot status={a.last_health_status} />
                        <span className="text-muted text-xs">
                          {a.last_health_ms ? `${a.last_health_ms} ms` : "—"}
                        </span>
                      </div>
                    </td>
                    <td className="text-muted text-xs">{a.updated_at?.slice(0, 10) || "—"}</td>
                    <td><IcChevronRight size={14} style={{ color: "var(--text-muted)" }} /></td>
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
