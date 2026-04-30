import React, { useEffect, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { agents as agentsApi, registry } from "../api/client.js";
import { Spinner, StatusBadge, HealthDot, TagList,
         Alert, EmptyState, ConfirmModal } from "./Primitives.jsx";
import { IcPlus, IcSearch, IcRefresh, IcEdit, IcTrash,
         IcChevronRight, IcDownload, IcFilter } from "./Icons.jsx";
import AgentForm from "./AgentForm.jsx";

const STATUS_FILTERS  = ["all","active","inactive","degraded"];
const UTILITY_FILTERS = ["all","electric","gas","water","multi"];

export default function AgentList() {
  const navigate            = useNavigate();
  const [searchParams, setSP] = useSearchParams();

  const [list,     setList]     = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editItem, setEditItem] = useState(null);
  const [deleteId, setDeleteId] = useState(null);
  const [toast,    setToast]    = useState("");

  const [q,      setQ]      = useState(searchParams.get("q")            || "");
  const [status, setStatus] = useState(searchParams.get("status")       || "all");
  const [utype,  setUtype]  = useState(searchParams.get("utility_type") || "all");

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(""), 2500); };

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const p = {
        q:            q.trim() || undefined,
        status:       status !== "all" ? status : undefined,
        utility_type: utype  !== "all" ? utype  : undefined,
      };
      const res = await agentsApi.list(p);
      setList(res.agents || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, status, utype]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const p = {};
    if (q)                p.q            = q;
    if (status !== "all") p.status       = status;
    if (utype  !== "all") p.utility_type = utype;
    setSP(p, { replace: true });
  }, [q, status, utype, setSP]);

  const handleDelete = async () => {
    try {
      await agentsApi.delete(deleteId);
      setDeleteId(null);
      showToast("Agent deactivated.");
      load();
    } catch (err) {
      setError(err.message);
      setDeleteId(null);
    }
  };

  const handleSaved = () => {
    setShowForm(false); setEditItem(null);
    showToast(editItem ? "Agent updated." : "Agent registered.");
    load();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div className="page-header">
        <div>
          <div className="page-title">Agents</div>
          <div className="page-desc">{list.length} agent{list.length !== 1 ? "s" : ""} found</div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn btn-secondary" onClick={() => registry.export()}>
            <IcDownload size={14} /> Export
          </button>
          <button className="btn btn-secondary" onClick={load}>
            <IcRefresh size={14} /> Refresh
          </button>
          <button className="btn btn-primary"
            onClick={() => { setEditItem(null); setShowForm(true); }}>
            <IcPlus size={14} /> Register agent
          </button>
        </div>
      </div>

      {toast && <div className="alert alert-success" style={{ padding: "10px 16px" }}>{toast}</div>}
      {error && <Alert type="error" onClose={() => setError("")}>{error}</Alert>}

      {/* Filters */}
      <div className="card">
        <div className="card-body" style={{ padding: "14px 16px",
          display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
          <div className="search-bar" style={{ maxWidth: 340 }}>
            <IcSearch size={15} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
            <input placeholder="Search name, description, capability…"
              value={q} onChange={e => setQ(e.target.value)} />
            {q && <button style={{ background: "none", border: "none", cursor: "pointer",
              color: "var(--text-muted)", fontSize: 18, lineHeight: 1 }}
              onClick={() => setQ("")}>×</button>}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <IcFilter size={13} style={{ color: "var(--text-muted)" }} />
            <span className="text-xs text-muted">Status:</span>
            <div className="filter-chips">
              {STATUS_FILTERS.map(s => (
                <span key={s} className={`chip ${status === s ? "selected" : ""}`}
                  onClick={() => setStatus(s)}>
                  {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
                </span>
              ))}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="text-xs text-muted">Utility:</span>
            <div className="filter-chips">
              {UTILITY_FILTERS.map(u => (
                <span key={u} className={`chip ${utype === u ? "selected" : ""}`}
                  onClick={() => setUtype(u)}>
                  {u === "all" ? "All" : u}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="card">
        {loading
          ? <div style={{ display: "flex", justifyContent: "center", padding: 48 }}>
              <Spinner large />
            </div>
          : list.length === 0
          ? <EmptyState icon="🤖" title="No agents found"
              desc="Try adjusting your filters or register a new agent."
              action={
                <button className="btn btn-primary"
                  onClick={() => { setEditItem(null); setShowForm(true); }}>
                  <IcPlus size={14} /> Register first agent
                </button>
              } />
          : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Agent</th><th>Status</th><th>Utility types</th>
                  <th>Capabilities</th><th>Tags</th>
                  <th>Health</th><th>Updated</th><th></th>
                </tr>
              </thead>
              <tbody>
                {list.map(a => (
                  <tr key={a.id} style={{ cursor: "pointer" }}
                    onClick={() => navigate(`/agents/${a.id}`)}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{a.name}</div>
                      <div className="text-xs text-muted" style={{ maxWidth: 220,
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {a.description}
                      </div>
                    </td>
                    <td><StatusBadge status={a.status} /></td>
                    <td>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        {(a.utility_types || []).map(t => (
                          <span key={t} className="badge"
                            style={{ background: "#f0fdf4", color: "#166534",
                              padding: "1px 7px", fontSize: 11 }}>{t}</span>
                        ))}
                      </div>
                    </td>
                    <td className="text-muted text-sm">{a.capabilities?.length || 0}</td>
                    <td><TagList tags={(a.tags || []).slice(0, 3)} /></td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <HealthDot status={a.last_health_status} />
                        <span className="text-xs text-muted">
                          {a.last_health_ms ? `${a.last_health_ms} ms` : a.last_health_status || "—"}
                        </span>
                      </div>
                    </td>
                    <td className="text-xs text-muted">{a.updated_at?.slice(0,10) || "—"}</td>
                    <td onClick={e => e.stopPropagation()}>
                      <div style={{ display: "flex", gap: 2 }}>
                        <button className="btn btn-ghost btn-icon btn-sm" title="Edit"
                          onClick={() => { setEditItem(a); setShowForm(true); }}>
                          <IcEdit size={14} />
                        </button>
                        <button className="btn btn-ghost btn-icon btn-sm" title="Deactivate"
                          style={{ color: "var(--c-danger)" }}
                          onClick={() => setDeleteId(a.id)}>
                          <IcTrash size={14} />
                        </button>
                        <IcChevronRight size={14} style={{ color: "var(--text-muted)" }} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showForm && (
        <AgentForm initial={editItem} onSaved={handleSaved}
          onCancel={() => { setShowForm(false); setEditItem(null); }} />
      )}
      {deleteId && (
        <ConfirmModal
          title="Deactivate agent"
          message="Sets status to inactive. Document is retained for audit. Use ?hard=true via CLI for permanent deletion."
          confirmLabel="Deactivate" danger
          onConfirm={handleDelete}
          onCancel={() => setDeleteId(null)} />
      )}
    </div>
  );
}
