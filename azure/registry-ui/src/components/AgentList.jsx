import React, { useEffect, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { agents as agentsApi, registry } from "../api/client.js";
import {
  Spinner, StatusBadge, HealthDot, TagList, Alert,
  EmptyState, ConfirmModal
} from "./Primitives.jsx";
import {
  IcPlus, IcSearch, IcRefresh, IcEdit, IcTrash,
  IcChevronRight, IcDownload, IcFilter, IcUpload
} from "./Icons.jsx";
import AgentForm from "./AgentForm.jsx";
import ImportAgentModal from "./ImportAgentModal.jsx";

const STATUS_FILTERS = ["all", "active", "inactive", "degraded"];
const UTILITY_FILTERS = ["all", "electric", "gas", "water", "multi"];

export default function AgentList() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [agentList, setAgentList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [editAgent, setEditAgent] = useState(null);
  const [deleteId, setDeleteId] = useState(null);
  const [toast, setToast] = useState("");

  const [q, setQ] = useState(searchParams.get("q") || "");
  const [status, setStatus] = useState(searchParams.get("status") || "all");
  const [utype, setUtype] = useState(searchParams.get("utility_type") || "all");

  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(""), 2500);
  };

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const params = {
        q: q.trim() || undefined,
        status: status !== "all" ? status : undefined,
        utility_type: utype !== "all" ? utype : undefined,
      };
      const res = await agentsApi.list(params);
      setAgentList(res.agents || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, status, utype]);

  useEffect(() => { load(); }, [load]);

  // Sync filters into URL so they are shareable / bookmarkable
  useEffect(() => {
    const p = {};
    if (q) p.q = q;
    if (status !== "all") p.status = status;
    if (utype !== "all") p.utility_type = utype;
    setSearchParams(p, { replace: true });
  }, [q, status, utype, setSearchParams]);

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
    setShowForm(false);
    setEditAgent(null);
    showToast(editAgent ? "Agent updated." : "Agent registered.");
    load();
  };

  // Called by ImportAgentModal with the count of successfully imported agents
  const handleImported = (count) => {
    showToast(`${count} agent${count !== 1 ? "s" : ""} imported successfully.`);
    load();
    // Keep the modal open so the user can review results — modal closes itself
    // when they click Close after seeing the results list.
  };

  const handleExport = async () => {
    try { await registry.export(); }
    catch (err) { setError(err.message); }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      {/* Page header */}
      <div className="page-header">
        <div>
          <div className="page-title">Agents</div>
          <div className="page-desc">
            {agentList.length} agent{agentList.length !== 1 ? "s" : ""} found
          </div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn btn-secondary" onClick={handleExport}>
            <IcDownload size={14} /> Export
          </button>
          <button className="btn btn-secondary" onClick={load}>
            <IcRefresh size={14} /> Refresh
          </button>
          {/* ── Import ── */}
          <button
            className="btn btn-secondary"
            onClick={() => setShowImport(true)}
          >
            <IcUpload size={14} /> Import
          </button>
          {/* ── Register (manual form) ── */}
          <button
            className="btn btn-primary"
            onClick={() => { setEditAgent(null); setShowForm(true); }}
          >
            <IcPlus size={14} /> Register agent
          </button>
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className="alert alert-success" style={{ padding: "10px 16px" }}>
          {toast}
        </div>
      )}

      {error && <Alert type="error" onClose={() => setError("")}>{error}</Alert>}

      {/* Filters */}
      <div className="card">
        <div className="card-body" style={{
          padding: "14px 16px", display: "flex",
          gap: 16, flexWrap: "wrap", alignItems: "center",
        }}>
          {/* Search */}
          <div className="search-bar" style={{ maxWidth: 320 }}>
            <IcSearch size={15} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
            <input
              placeholder="Search name, description, capability…"
              value={q}
              onChange={e => setQ(e.target.value)}
            />
            {q && (
              <button
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: "var(--text-muted)", fontSize: 16, lineHeight: 1
                }}
                onClick={() => setQ("")}>×</button>
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <IcFilter size={13} style={{ color: "var(--text-muted)" }} />
            <span style={{ fontSize: 12, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
              Status:
            </span>
            <div className="filter-chips">
              {STATUS_FILTERS.map(s => (
                <span key={s}
                  className={`chip ${status === s ? "selected" : ""}`}
                  onClick={() => setStatus(s)}>
                  {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
                </span>
              ))}
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 12, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
              Utility:
            </span>
            <div className="filter-chips">
              {UTILITY_FILTERS.map(u => (
                <span key={u}
                  className={`chip ${utype === u ? "selected" : ""}`}
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
          ? (
            <div style={{ display: "flex", justifyContent: "center", padding: 48 }}>
              <Spinner large />
            </div>
          )
          : agentList.length === 0
            ? (
              <EmptyState
                icon="🤖"
                title="No agents found"
                desc="Try adjusting your filters, register a new agent, or import from a JSON file."
                action={
                  <div style={{ display: "flex", gap: 10 }}>
                    <button className="btn btn-secondary"
                      onClick={() => setShowImport(true)}>
                      <IcUpload size={13} /> Import
                    </button>
                    <button className="btn btn-primary"
                      onClick={() => { setEditAgent(null); setShowForm(true); }}>
                      <IcPlus size={13} /> Register first agent
                    </button>
                  </div>
                }
              />
            )
            : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Agent</th>
                      <th>Status</th>
                      <th>Utility types</th>
                      <th>Capabilities</th>
                      <th>Tags</th>
                      <th>Health</th>
                      <th>Updated</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {agentList.map(a => (
                      <tr key={a.id} style={{ cursor: "pointer" }}
                        onClick={() => navigate(`/agents/${a.id}`)}>
                        <td>
                          <div style={{ fontWeight: 600, fontSize: 14 }}>{a.name}</div>
                          <div style={{
                            fontSize: 11, color: "var(--text-muted)",
                            maxWidth: 220, overflow: "hidden",
                            textOverflow: "ellipsis", whiteSpace: "nowrap"
                          }}>
                            {a.description}
                          </div>
                        </td>
                        <td><StatusBadge status={a.status} /></td>
                        <td>
                          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                            {(a.utility_types || []).map(t => (
                              <span key={t} className="badge" style={{
                                background: "#f0fdf4", color: "#166534",
                                padding: "1px 7px", fontSize: 11,
                              }}>{t}</span>
                            ))}
                          </div>
                        </td>
                        <td>
                          <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>
                            {a.capabilities?.length || 0}
                          </span>
                        </td>
                        <td><TagList tags={(a.tags || []).slice(0, 3)} /></td>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <HealthDot status={a.last_health_status} />
                            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                              {a.last_health_ms
                                ? `${a.last_health_ms} ms`
                                : a.last_health_status || "—"}
                            </span>
                          </div>
                        </td>
                        <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                          {a.updated_at?.slice(0, 10) || "—"}
                        </td>
                        <td onClick={e => e.stopPropagation()}>
                          <div style={{ display: "flex", gap: 4 }}>
                            <button className="btn btn-ghost btn-icon btn-sm"
                              title="Edit"
                              onClick={() => { setEditAgent(a); setShowForm(true); }}>
                              <IcEdit size={14} />
                            </button>
                            <button className="btn btn-ghost btn-icon btn-sm"
                              title="Deactivate"
                              style={{ color: "var(--c-danger)" }}
                              onClick={() => setDeleteId(a.id)}>
                              <IcTrash size={14} />
                            </button>
                            <IcChevronRight size={14}
                              style={{ color: "var(--text-muted)" }} />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
        }
      </div>

      {/* ── Modals ── */}

      {showForm && (
        <AgentForm
          initial={editAgent}
          onSaved={handleSaved}
          onCancel={() => { setShowForm(false); setEditAgent(null); }}
        />
      )}

      {showImport && (
        <ImportAgentModal
          onImported={handleImported}
          onCancel={() => setShowImport(false)}
        />
      )}

      {deleteId && (
        <ConfirmModal
          title="Deactivate agent"
          message="This will soft-delete the agent (status → inactive). It remains in the database for audit. To permanently remove, use the CLI with ?hard=true."
          confirmLabel="Deactivate"
          danger
          onConfirm={handleDelete}
          onCancel={() => setDeleteId(null)}
        />
      )}
    </div>
  );
}