import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { agents as agentsApi } from "../api/client.js";
import { Spinner, StatusBadge, HealthDot, TagList,
         Alert, ConfirmModal, CopyButton } from "./Primitives.jsx";
import { IcEdit, IcTrash, IcZap, IcChevronRight, IcLink, IcPlus } from "./Icons.jsx";
import AgentForm from "./AgentForm.jsx";
import { AuthTypeBadge } from "./AuthConfigSection.jsx";

const STATUS_OPTIONS = ["active", "inactive", "degraded"];

const HC_COLORS = {
  http: { bg: "#e0f2fe", color: "#0369a1" },
  tcp:  { bg: "#fef9c3", color: "#854d0e" },
  none: { bg: "#f1f5f9", color: "#334155" },
};

function HcBadge({ type }) {
  const { bg, color } = HC_COLORS[type] || HC_COLORS.http;
  return (
    <span style={{ background: bg, color, padding: "3px 10px",
      borderRadius: 99, fontSize: 12, fontWeight: 500 }}>
      {type || "http"}
    </span>
  );
}

// ── Auth display ─────────────────────────────────────────────────────────────
function AuthDisplay({ agent }) {
  const cfg      = agent.auth_config || {};
  const authType = cfg.auth_type || "none";

  const rows = [];
  if (authType === "api_key") {
    rows.push(["Location",   cfg.api_key_location || "header",    false]);
    rows.push(["Key name",   cfg.api_key_name     || "—",         false]);
    rows.push(["KV secret",  cfg.api_key_secret_name || "not set", true]);
  }
  if (authType === "bearer_token") {
    rows.push(["KV secret",  cfg.bearer_token_secret_name || "not set", true]);
  }
  if (authType === "basic_auth") {
    rows.push(["Username",   cfg.basic_auth_username || "—",              false]);
    rows.push(["KV secret",  cfg.basic_auth_password_secret_name || "not set", true]);
  }
  if (authType === "oauth2") {
    rows.push(["Token URL",  cfg.oauth2_token_url  || "—",               false]);
    rows.push(["Client ID",  cfg.oauth2_client_id  || "—",               false]);
    rows.push(["KV secret",  cfg.oauth2_client_secret_name || "not set",  true]);
    if (cfg.oauth2_scopes) rows.push(["Scopes", cfg.oauth2_scopes,        false]);
    rows.push(["Token TTL",  `${cfg.oauth2_token_ttl_seconds || 3600} s`, false]);
  }
  if (authType === "custom" && (cfg.custom_entries || []).length > 0) {
    cfg.custom_entries.forEach((e, i) => {
      const v = e.secret_name ? `KV: ${e.secret_name}` : (e.value ? `plain: ${e.value}` : "—");
      rows.push([`[${i+1}] ${e.key} (${e.inject_as})`, v, Boolean(e.secret_name)]);
    });
  }
  if (authType === "none" && agent.api_key_secret_name) {
    rows.push(["Legacy KV secret", agent.api_key_secret_name, true]);
  }

  return (
    <SectionBlock title="Authentication">
      <div style={{ marginBottom: 8 }}><AuthTypeBadge authType={authType} /></div>
      {rows.map(([label, value, isSecret]) => (
        <KeyVal key={label} label={label} value={value} isSecret={isSecret} />
      ))}
      {rows.length === 0 && authType === "none" && !agent.api_key_secret_name && (
        <span className="text-xs text-muted" style={{ fontStyle: "italic" }}>
          No authentication configured.
        </span>
      )}
    </SectionBlock>
  );
}

// ── Health check display ─────────────────────────────────────────────────────
function HealthDisplay({ agent }) {
  const hc        = agent.health_check_config || {};
  const checkType = hc.check_type || "http";
  const rows      = [];

  if (checkType === "http") {
    rows.push(["Health URL", hc.health_check_url || "auto-derived"]);
    rows.push(["Expected status", String(hc.expected_http_status || 200)]);
    rows.push(["HTTP timeout", `${hc.http_timeout_seconds || 10} s`]);
  } else if (checkType === "tcp") {
    rows.push(["TCP port",    String(hc.tcp_port || "auto-detected")]);
    rows.push(["TCP timeout", `${hc.tcp_timeout_seconds || 5} s`]);
  }

  return (
    <SectionBlock title="Health check">
      <div style={{ marginBottom: 8 }}><HcBadge type={checkType} /></div>
      {rows.map(([l, v]) => <KeyVal key={l} label={l} value={v} />)}
      {checkType === "none" && (
        <span className="text-xs text-muted" style={{ fontStyle: "italic" }}>
          No health probing — always healthy.
        </span>
      )}
    </SectionBlock>
  );
}

// ── Invocation config display ─────────────────────────────────────────────────
function InvocationDisplay({ agent }) {
  const inv  = agent.invocation_config || {};
  const tpl  = inv.body_template || {};
  const hdrs = inv.extra_static_headers || {};

  return (
    <SectionBlock title="Invocation">
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <span className="badge" style={{ background: "#ede9fe", color: "#5b21b6", padding: "3px 8px" }}>
          {inv.http_method || "POST"}
        </span>
        <span className="badge" style={{ background: "#f1f5f9", color: "#334155", padding: "3px 8px", fontSize: 11 }}>
          {inv.content_type || "application/json"}
        </span>
        {(inv.timeout_seconds || 0) > 0 && (
          <span className="badge" style={{ background: "#fef3c7", color: "#92400e", padding: "3px 8px", fontSize: 11 }}>
            timeout {inv.timeout_seconds}s
          </span>
        )}
        {(inv.max_retries ?? -1) >= 0 && (
          <span className="badge" style={{ background: "#dcfce7", color: "#15803d", padding: "3px 8px", fontSize: 11 }}>
            {inv.max_retries} retries
          </span>
        )}
      </div>

      {Object.keys(tpl).length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div className="text-xs text-muted" style={{ marginBottom: 4 }}>Body fields</div>
          {Object.entries(tpl).map(([k, v]) => (
            <div key={k} style={{ display: "flex", gap: 6, fontSize: 11, marginBottom: 3 }}>
              <code style={{ color: "var(--c-primary)", minWidth: 80 }}>{k}</code>
              <span style={{ color: "var(--text-muted)" }}>→</span>
              <code style={{ color: "var(--text-secondary)" }}>
                {typeof v === "string" ? v : JSON.stringify(v)}
              </code>
            </div>
          ))}
        </div>
      )}

      {inv.response_result_path && (
        <div style={{ marginBottom: 8 }}>
          <div className="text-xs text-muted" style={{ marginBottom: 2 }}>Result path</div>
          <code style={{ fontSize: 11, color: "var(--c-primary)" }}>
            {inv.response_result_path}
          </code>
        </div>
      )}

      {Object.keys(hdrs).length > 0 && (
        <div>
          <div className="text-xs text-muted" style={{ marginBottom: 4 }}>Static headers</div>
          {Object.entries(hdrs).map(([k, v]) => (
            <KeyVal key={k} label={k} value={v} />
          ))}
        </div>
      )}

      {Object.keys(tpl).length === 0 && !inv.response_result_path && Object.keys(hdrs).length === 0 && (
        <span className="text-xs text-muted" style={{ fontStyle: "italic" }}>
          Default invocation schema (task, session_id, customer_id, context).
        </span>
      )}
    </SectionBlock>
  );
}

// ── Shared display helpers ────────────────────────────────────────────────────
function SectionBlock({ title, children }) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
        textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {children}
      </div>
    </div>
  );
}

function KeyVal({ label, value, isSecret }) {
  return (
    <div style={{ display: "flex", gap: 8, fontSize: 12 }}>
      <span style={{ color: "var(--text-muted)", minWidth: 110, flexShrink: 0, fontSize: 11 }}>
        {label}
      </span>
      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
        {isSecret && (
          <span style={{ width: 6, height: 6, borderRadius: "50%",
            background: "var(--c-success)", display: "inline-block", flexShrink: 0 }}
            title="Stored in Key Vault" />
        )}
        <code style={{ color: "var(--text-secondary)", wordBreak: "break-all",
          background: "var(--bg-page)", padding: "1px 5px", borderRadius: 4, fontSize: 11 }}>
          {value}
        </code>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function AgentDetail() {
  const { id }   = useParams();
  const navigate = useNavigate();

  const [agent,      setAgent]      = useState(null);
  const [loading,    setLoading]    = useState(true);
  const [pinging,    setPinging]    = useState(false);
  const [pingRes,    setPingRes]    = useState(null);
  const [error,      setError]      = useState("");
  const [toast,      setToast]      = useState("");
  const [showEdit,   setShowEdit]   = useState(false);
  const [showDel,    setShowDel]    = useState(false);
  const [statusBusy, setStatusBusy] = useState(false);
  const [capOpen,    setCapOpen]    = useState(false);
  const [newCap,     setNewCap]     = useState({ name: "", description: "" });

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(""), 2500); };

  const load = async () => {
    setLoading(true); setError("");
    try { setAgent(await agentsApi.get(id)); }
    catch (err) { setError(err.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [id]);

  const handlePing = async () => {
    setPinging(true); setPingRes(null);
    try { setPingRes(await agentsApi.ping(id)); await load(); }
    catch (err) { setPingRes({ status: "unreachable", error: err.message }); }
    finally { setPinging(false); }
  };

  const handleStatus = async (e) => {
    setStatusBusy(true);
    try { await agentsApi.setStatus(id, e.target.value); await load(); showToast(`Status → ${e.target.value}.`); }
    catch (err) { setError(err.message); }
    finally { setStatusBusy(false); }
  };

  const handleDelete = async () => {
    await agentsApi.delete(id);
    navigate("/agents");
  };

  const handleRemoveCap = async (name) => {
    try { await agentsApi.removeCapability(id, name); await load(); showToast(`Capability "${name}" removed.`); }
    catch (err) { setError(err.message); }
  };

  const handleAddCap = async (e) => {
    e.preventDefault();
    if (!newCap.name.trim()) return;
    try {
      await agentsApi.addCapability(id, { ...newCap, input_schema: {}, output_schema: {} });
      setNewCap({ name: "", description: "" }); setCapOpen(false);
      await load(); showToast(`Capability "${newCap.name}" added.`);
    } catch (err) { setError(err.message); }
  };

  if (loading) return <div style={{ display: "flex", justifyContent: "center", padding: 60 }}><Spinner large /></div>;

  if (!agent) return (
    <div className="card"><div className="card-body">
      <p className="text-muted">Agent not found.</p>
      <button className="btn btn-secondary" style={{ marginTop: 12 }}
        onClick={() => navigate("/agents")}>← Back to agents</button>
    </div></div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      {/* Breadcrumb */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--text-muted)" }}>
        <button className="btn btn-ghost btn-sm" style={{ padding: "4px 8px" }}
          onClick={() => navigate("/agents")}>Agents</button>
        <IcChevronRight size={12} />
        <span style={{ color: "var(--text-primary)" }}>{agent.name}</span>
      </div>

      {toast && <div className="alert alert-success" style={{ padding: "10px 16px" }}>{toast}</div>}
      {error && <Alert type="error" onClose={() => setError("")}>{error}</Alert>}

      {pingRes && (
        <div className={`alert ${pingRes.status === "healthy" ? "alert-success" : "alert-error"}`}>
          Ping: <strong>{pingRes.status}</strong>
          {pingRes.check_type && ` (${pingRes.check_type})`}
          {pingRes.response_ms != null && ` · ${pingRes.response_ms} ms`}
          {pingRes.http_code && ` · HTTP ${pingRes.http_code}`}
          {pingRes.error && ` · ${pingRes.error}`}
        </div>
      )}

      {/* Header */}
      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, flex: 1, minWidth: 0 }}>
            <div style={{ width: 44, height: 44, borderRadius: "var(--radius-sm)",
              background: "var(--c-primary-light)", display: "flex",
              alignItems: "center", justifyContent: "center", fontSize: 20, flexShrink: 0 }}>🤖</div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 20, fontWeight: 700, display: "flex",
                alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                {agent.name}<StatusBadge status={agent.status} />
              </div>
              <div className="text-sm text-muted truncate" style={{ maxWidth: 500 }}>
                {agent.description}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
            <button className="btn btn-secondary btn-sm" onClick={handlePing} disabled={pinging}>
              {pinging ? <Spinner /> : <IcZap size={13} />}
              {pinging ? "Pinging…" : "Ping"}
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => setShowEdit(true)}>
              <IcEdit size={13} /> Edit
            </button>
            <button className="btn btn-danger btn-sm" onClick={() => setShowDel(true)}>
              <IcTrash size={13} /> Deactivate
            </button>
          </div>
        </div>

        <div className="card-body">
          {/* Top row: endpoint + basic metadata */}
          <div style={{ marginBottom: 20 }}>
            <SectionBlock title="Endpoint URL">
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <IcLink size={13} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
                <code style={{ fontSize: 12, color: "var(--c-primary)", wordBreak: "break-all", flex: 1 }}>
                  {agent.endpoint_url}
                </code>
                <CopyButton text={agent.endpoint_url} />
              </div>
            </SectionBlock>
          </div>

          {/* Three-column detail grid */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 24 }}>

            {/* Column 1 */}
            <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
                  textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>Utility types</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {(agent.utility_types || []).map(t => (
                    <span key={t} className="badge"
                      style={{ background: "#f0fdf4", color: "#166534", padding: "3px 10px" }}>{t}</span>
                  ))}
                  {!agent.utility_types?.length && <span className="text-muted text-sm">—</span>}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
                  textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>Tags</div>
                <TagList tags={agent.tags} />
              </div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
                  textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>Version</div>
                <span className="badge badge-tag">v{agent.version}</span>
              </div>
            </div>

            {/* Column 2: auth + health check */}
            <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              <AuthDisplay agent={agent} />
              <HealthDisplay agent={agent} />
            </div>

            {/* Column 3: invocation + status controls */}
            <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              <InvocationDisplay agent={agent} />

              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
                  textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>Set status</div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <select className="form-control" value={agent.status}
                    onChange={handleStatus} disabled={statusBusy}
                    style={{ width: "auto", minWidth: 130, fontSize: 13 }}>
                    {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                  {statusBusy && <Spinner />}
                </div>
              </div>

              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
                  textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>Last health</div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <HealthDot status={agent.last_health_status} />
                  <span className="text-sm text-muted">
                    {agent.last_health_status || "Never checked"}
                    {agent.last_health_ms != null && ` · ${agent.last_health_ms} ms`}
                  </span>
                </div>
                {agent.last_health_check_at && (
                  <div className="text-xs text-muted" style={{ marginTop: 3 }}>
                    {agent.last_health_check_at.slice(0,19).replace("T"," ")} UTC
                  </div>
                )}
              </div>

              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
                  textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>Agent ID</div>
                <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <code className="font-mono text-muted" style={{ fontSize: 10, wordBreak: "break-all" }}>
                    {agent.id}
                  </code>
                  <CopyButton text={agent.id} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Capabilities */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">
            Capabilities
            <span className="text-muted text-sm" style={{ marginLeft: 8, fontWeight: 400 }}>
              {agent.capabilities?.length || 0}
            </span>
          </span>
          <button className="btn btn-secondary btn-sm" onClick={() => setCapOpen(v => !v)}>
            <IcPlus size={13} /> {capOpen ? "Cancel" : "Add capability"}
          </button>
        </div>
        <div className="card-body">
          {capOpen && (
            <form onSubmit={handleAddCap} style={{ marginBottom: 16, padding: 16,
              background: "var(--bg-page)", borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: 12 }}>
              <div className="grid-2">
                <div className="form-group">
                  <label className="form-label" style={{ fontSize: 12 }}>Name</label>
                  <input className="form-control" value={newCap.name} autoFocus
                    onChange={e => setNewCap(c => ({ ...c, name: e.target.value }))}
                    placeholder="e.g. check_balance" />
                </div>
                <div className="form-group">
                  <label className="form-label" style={{ fontSize: 12 }}>Description</label>
                  <input className="form-control" value={newCap.description}
                    onChange={e => setNewCap(c => ({ ...c, description: e.target.value }))}
                    placeholder="What this capability does" />
                </div>
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                <button type="button" className="btn btn-secondary btn-sm"
                  onClick={() => setCapOpen(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary btn-sm">Add</button>
              </div>
            </form>
          )}
          {!agent.capabilities?.length
            ? <p className="text-muted text-sm" style={{ fontStyle: "italic" }}>
                No capabilities defined.
              </p>
            : (
            <div className="capability-list">
              {agent.capabilities.map(cap => (
                <div key={cap.name} className="capability-item">
                  <div style={{ flex: 1 }}>
                    <div className="cap-name">{cap.name}</div>
                    <div className="cap-desc">{cap.description || "—"}</div>
                  </div>
                  <button className="btn btn-ghost btn-icon btn-sm"
                    style={{ color: "var(--c-danger)" }}
                    onClick={() => handleRemoveCap(cap.name)} title="Remove">
                    <IcTrash size={13} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="text-xs text-muted" style={{ textAlign: "center", padding: "4px 0" }}>
        Created {agent.created_at?.slice(0,10)} ·
        Last updated {agent.updated_at?.slice(0,19).replace("T"," ")} UTC
      </div>

      {showEdit && (
        <AgentForm initial={agent}
          onSaved={() => { setShowEdit(false); load(); showToast("Agent updated."); }}
          onCancel={() => setShowEdit(false)} />
      )}
      {showDel && (
        <ConfirmModal title={`Deactivate ${agent.name}?`}
          message="Sets to inactive — retained for audit."
          confirmLabel="Deactivate" danger
          onConfirm={handleDelete} onCancel={() => setShowDel(false)} />
      )}
    </div>
  );
}
