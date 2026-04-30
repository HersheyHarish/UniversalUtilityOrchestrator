import React, { useState } from "react";
import { agents as agentsApi } from "../api/client.js";
import { Spinner, Alert, TooltipIcon } from "./Primitives.jsx";
import { IcPlus, IcTrash, IcRefresh, IcZap } from "./Icons.jsx";
import AuthConfigSection, {
  DEFAULT_AUTH_CONFIG,
  DEFAULT_AUTH_SECRETS,
} from "./AuthConfigSection.jsx";
import {
  HealthCheckSection,
  InvocationSection,
  DEFAULT_HEALTH,
  DEFAULT_INVOCATION,
} from "./InvocationConfigSection.jsx";

const UTILITY_TYPES = ["electric", "gas", "water", "multi"];

const TIPS = {
  name:    "Unique identifier. PascalCase, no spaces. e.g. BillingAgent.",
  desc:    "Sent verbatim to the planner LLM. Be specific.",
  url:     "Full invoke URL. e.g. https://fn-billing-ua001.azurewebsites.net/api/invoke",
  version: "Semantic version. e.g. 1.2.0",
  tags:    "Comma-separated labels. e.g. billing, payments",
  capName: "snake_case identifier. e.g. explain_bill",
  capDesc: "What this capability does. One sentence.",
};

const TABS = [
  { id: "basic",        label: "Basic info" },
  { id: "auth",         label: "Auth" },
  { id: "invocation",   label: "Invocation" },
  { id: "health",       label: "Health check" },
  { id: "capabilities", label: "Capabilities" },
];

function CapRow({ cap, onChange, onRemove }) {
  return (
    <div style={{
      padding: "12px 14px", borderRadius: "var(--radius-sm)",
      background: "var(--bg-page)", border: "1px solid var(--border)",
      display: "flex", flexDirection: "column", gap: 10,
    }}>
      <div className="grid-2">
        <div className="form-group">
          <label className="form-label" style={{ fontSize: 11 }}>
            Name <TooltipIcon text={TIPS.capName} />
          </label>
          <input className="form-control" value={cap.name} style={{ fontSize: 13 }}
            placeholder="e.g. explain_bill"
            onChange={e => onChange({ ...cap, name: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="form-label" style={{ fontSize: 11 }}>
            Description <TooltipIcon text={TIPS.capDesc} />
          </label>
          <input className="form-control" value={cap.description} style={{ fontSize: 13 }}
            placeholder="What this capability does"
            onChange={e => onChange({ ...cap, description: e.target.value })} />
        </div>
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button type="button" className="btn btn-danger btn-sm" onClick={onRemove}>
          <IcTrash size={12} /> Remove
        </button>
      </div>
    </div>
  );
}

export default function AgentForm({ initial, onSaved, onCancel }) {
  const isEdit = Boolean(initial?.id);

  const [form, setForm] = useState({
    name:          initial?.name || "",
    description:   initial?.description || "",
    endpoint_url:  initial?.endpoint_url || "",
    version:       initial?.version || "1.0.0",
    utility_types: initial?.utility_types || [],
    tags:          (initial?.tags || []).join(", "),
    capabilities:  initial?.capabilities || [],
  });

  const [authConfig,       setAuthConfig]       = useState(
    { ...DEFAULT_AUTH_CONFIG, ...(initial?.auth_config || {}) }
  );
  const [authSecrets,      setAuthSecrets]      = useState({ ...DEFAULT_AUTH_SECRETS });
  const [healthConfig,     setHealthConfig]     = useState(
    { ...DEFAULT_HEALTH, ...(initial?.health_check_config || {}) }
  );
  const [invocationConfig, setInvocationConfig] = useState(
    { ...DEFAULT_INVOCATION, ...(initial?.invocation_config || {}) }
  );

  const [error,        setError]       = useState("");
  const [loading,      setLoading]     = useState(false);
  const [activeTab,    setActiveTab]   = useState("basic");

  // Auto-fetch state
  const [fetching,     setFetching]    = useState(false);
  const [fetchError,   setFetchError]  = useState("");
  const [fetchWarning, setFetchWarning] = useState("");
  const [rawPreview,   setRawPreview]  = useState("");
  const [showRaw,      setShowRaw]     = useState(false);
  const [fetchSuccess, setFetchSuccess] = useState(false);

  const set  = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const setU = (t)    => set("utility_types",
    form.utility_types.includes(t)
      ? form.utility_types.filter(u => u !== t)
      : [...form.utility_types, t]
  );

  const addCap    = () => set("capabilities", [
    ...form.capabilities, { name: "", description: "", input_schema: {}, output_schema: {} },
  ]);
  const updateCap = (i, v) =>
    set("capabilities", form.capabilities.map((c, idx) => idx === i ? v : c));
  const removeCap = (i) =>
    set("capabilities", form.capabilities.filter((_, idx) => idx !== i));

  // ── Auto-fetch handler ──────────────────────────────────────────────────────
  const handleFetchCapabilities = async () => {
    setFetchError("");
    setFetchWarning("");
    setRawPreview("");
    setFetchSuccess(false);
    setShowRaw(false);

    const url = form.endpoint_url.trim();
    if (!url) {
      setFetchError("Enter an endpoint URL on the Basic info tab first.");
      return;
    }
    if (!url.startsWith("http")) {
      setFetchError("Endpoint URL must start with https:// or http://");
      return;
    }

    setFetching(true);
    try {
      const result = await agentsApi.fetchCapabilities(
        url,
        authConfig,
        authSecrets,
        invocationConfig,
      );

      // Merge fetched capabilities with any already defined.
      // Existing caps with the same name are updated; new ones are appended.
      const existingNames = new Set(form.capabilities.map(c => c.name));
      const incoming      = result.capabilities || [];
      const toAdd         = incoming.filter(c => !existingNames.has(c.name));
      const merged        = [
        ...form.capabilities.map(c => {
          const updated = incoming.find(i => i.name === c.name);
          return updated ? { ...c, ...updated } : c;
        }),
        ...toAdd,
      ];
      set("capabilities", merged);

      if (result.warning)    setFetchWarning(result.warning);
      if (result.raw_response) setRawPreview(result.raw_response);
      setFetchSuccess(true);

    } catch (err) {
      setFetchError(err.message || "Auto-fetch failed.");
    } finally {
      setFetching(false);
    }
  };

  // ── Form submit ─────────────────────────────────────────────────────────────
  const hasSecrets = Boolean(
    authSecrets.api_key_value || authSecrets.bearer_token_value ||
    authSecrets.basic_auth_password_value || authSecrets.oauth2_client_secret_value ||
    (authSecrets.custom_secret_values || []).some(Boolean)
  );

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (!form.name.trim())         return setError("Agent name is required.");
    if (!form.description.trim())  return setError("Description is required.");
    if (!form.endpoint_url.trim()) return setError("Endpoint URL is required.");
    if (!form.endpoint_url.startsWith("http"))
      return setError("Endpoint URL must start with https://");

    const payload = {
      ...form,
      tags:                form.tags.split(",").map(t => t.trim()).filter(Boolean),
      capabilities:        form.capabilities.filter(c => c.name.trim()),
      auth_config:         authConfig,
      auth_secrets:        hasSecrets ? authSecrets : null,
      health_check_config: healthConfig,
      invocation_config:   invocationConfig,
    };

    setLoading(true);
    try {
      const result = isEdit
        ? await agentsApi.patch(initial.id, payload)
        : await agentsApi.create(payload);
      onSaved(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // ── Tab style ───────────────────────────────────────────────────────────────
  const tabStyle = (tab) => ({
    padding: "8px 14px", fontSize: 13,
    fontWeight: activeTab === tab ? 600 : 400,
    color: activeTab === tab ? "var(--c-primary)" : "var(--text-secondary)",
    background: "none", border: "none",
    borderBottom: activeTab === tab ? "2px solid var(--c-primary)" : "2px solid transparent",
    cursor: "pointer", transition: "all var(--transition)", whiteSpace: "nowrap",
  });

  const badge = (text) => (
    <span style={{
      marginLeft: 5, padding: "1px 5px", borderRadius: 99, fontSize: 10, fontWeight: 600,
      background: "var(--c-primary-light)", color: "var(--c-primary-text)",
    }}>{text}</span>
  );

  const canFetch = Boolean(form.endpoint_url.trim());

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" style={{ maxWidth: 720 }} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="modal-header">
          <div>
            <div className="modal-title">
              {isEdit ? `Edit — ${initial.name}` : "Register new agent"}
            </div>
            <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 3 }}>
              {isEdit ? "Update configuration" : "Add a remote agent to the registry"}
            </div>
          </div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onCancel}>×</button>
        </div>

        {/* Tab bar */}
        <div style={{
          display: "flex", borderBottom: "1px solid var(--border)",
          padding: "0 20px", gap: 0, overflowX: "auto",
        }}>
          {TABS.map(t => (
            <button key={t.id} style={tabStyle(t.id)} onClick={() => setActiveTab(t.id)}>
              {t.label}
              {t.id === "auth"         && authConfig.auth_type !== "none"                    && badge(authConfig.auth_type)}
              {t.id === "health"       && healthConfig.check_type !== "http"                 && badge(healthConfig.check_type)}
              {t.id === "invocation"   && Object.keys(invocationConfig.body_template||{}).length > 0 &&
                badge(Object.keys(invocationConfig.body_template).length + " fields")}
              {t.id === "capabilities" && form.capabilities.length > 0                       && badge(form.capabilities.length)}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {error && <Alert type="error" onClose={() => setError("")}>{error}</Alert>}

            {/* ── Basic tab ─────────────────────────────────────────────── */}
            {activeTab === "basic" && (
              <>
                <div className="grid-2">
                  <div className="form-group">
                    <label className="form-label">
                      Name <span className="form-required">*</span>
                      <TooltipIcon text={TIPS.name} />
                    </label>
                    <input className="form-control" value={form.name}
                      onChange={e => set("name", e.target.value)}
                      placeholder="e.g. BillingAgent" disabled={isEdit} />
                    {isEdit && <span className="form-hint">Name cannot be changed after creation.</span>}
                  </div>
                  <div className="form-group">
                    <label className="form-label">Version</label>
                    <input className="form-control" value={form.version}
                      onChange={e => set("version", e.target.value)} placeholder="1.0.0" />
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">
                    Description <span className="form-required">*</span>
                    <TooltipIcon text={TIPS.desc} />
                  </label>
                  <textarea className="form-control" value={form.description} rows={3}
                    onChange={e => set("description", e.target.value)}
                    placeholder="What does this agent do? Sent to the planner LLM." />
                </div>

                <div className="form-group">
                  <label className="form-label">
                    Endpoint URL <span className="form-required">*</span>
                    <TooltipIcon text={TIPS.url} />
                  </label>
                  <input className="form-control" value={form.endpoint_url}
                    onChange={e => set("endpoint_url", e.target.value)}
                    placeholder="https://fn-myagent-ua001.azurewebsites.net/api/invoke" />
                </div>

                <div className="form-group">
                  <label className="form-label">Utility types</label>
                  <div className="filter-chips">
                    {UTILITY_TYPES.map(t => (
                      <span key={t} className={`chip ${form.utility_types.includes(t) ? "selected" : ""}`}
                        onClick={() => setU(t)}>{t}</span>
                    ))}
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">
                    Tags <TooltipIcon text={TIPS.tags} />
                  </label>
                  <input className="form-control" value={form.tags}
                    onChange={e => set("tags", e.target.value)}
                    placeholder="billing, payments, usage  (comma-separated)" />
                </div>
              </>
            )}

            {/* ── Auth tab ──────────────────────────────────────────────── */}
            {activeTab === "auth" && (
              <AuthConfigSection
                config={authConfig} secrets={authSecrets}
                onChangeConfig={setAuthConfig} onChangeSecrets={setAuthSecrets}
              />
            )}

            {/* ── Invocation tab ────────────────────────────────────────── */}
            {activeTab === "invocation" && (
              <InvocationSection
                config={invocationConfig}
                onChange={setInvocationConfig}
              />
            )}

            {/* ── Health check tab ──────────────────────────────────────── */}
            {activeTab === "health" && (
              <HealthCheckSection
                config={healthConfig}
                onChange={setHealthConfig}
              />
            )}

            {/* ── Capabilities tab ──────────────────────────────────────── */}
            {activeTab === "capabilities" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

                {/* Auto-fetch section */}
                <div style={{
                  padding: 16, borderRadius: "var(--radius)",
                  border: "1px solid var(--border)",
                  background: "var(--bg-page)",
                  display: "flex", flexDirection: "column", gap: 12,
                }}>
                  <div style={{ display: "flex", alignItems: "flex-start",
                    justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
                        Auto-fetch capabilities
                      </div>
                      <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6 }}>
                        Sends a discovery prompt to the agent using the endpoint URL,
                        auth, and invocation settings you've configured.
                        {!canFetch && (
                          <span style={{ color: "var(--c-warning-text)", marginLeft: 6 }}>
                            Enter an endpoint URL first.
                          </span>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={handleFetchCapabilities}
                      disabled={fetching || !canFetch}
                      style={{ flexShrink: 0 }}
                    >
                      {fetching
                        ? <><Spinner /> Fetching…</>
                        : <><IcZap size={14} /> Auto-fetch capabilities</>
                      }
                    </button>
                  </div>

                  {/* Fetch error */}
                  {fetchError && (
                    <div style={{
                      padding: "12px 14px", borderRadius: "var(--radius-sm)",
                      background: "var(--c-danger-bg)", color: "var(--c-danger-text)",
                      border: "1px solid var(--c-danger)",
                      fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap",
                      display: "flex", flexDirection: "column", gap: 8,
                    }}>
                      <div style={{ display: "flex", alignItems: "flex-start",
                        justifyContent: "space-between", gap: 10 }}>
                        <div>
                          <div style={{ fontWeight: 600, marginBottom: 4 }}>Fetch failed</div>
                          <div>{fetchError}</div>
                        </div>
                        <button type="button"
                          onClick={() => setFetchError("")}
                          style={{ background: "none", border: "none",
                            cursor: "pointer", fontSize: 18, lineHeight: 1,
                            color: "var(--c-danger-text)", opacity: .6, flexShrink: 0 }}>
                          ×
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Fetch warning (non-fatal) */}
                  {fetchWarning && !fetchError && (
                    <div style={{
                      padding: "10px 14px", borderRadius: "var(--radius-sm)",
                      background: "var(--c-warning-bg)", color: "var(--c-warning-text)",
                      border: "1px solid var(--c-warning)", fontSize: 12,
                    }}>
                      <strong>Note:</strong> {fetchWarning}
                    </div>
                  )}

                  {/* Fetch success */}
                  {fetchSuccess && !fetchError && (
                    <div style={{
                      padding: "10px 14px", borderRadius: "var(--radius-sm)",
                      background: "var(--c-success-bg)", color: "var(--c-success-text)",
                      border: "1px solid var(--c-success)", fontSize: 13,
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                    }}>
                      <span>
                        ✓ {form.capabilities.length} capability{form.capabilities.length !== 1 ? "ies" : "y"} loaded.
                        Review and edit below before saving.
                      </span>
                      {rawPreview && (
                        <button type="button" className="btn btn-ghost btn-sm"
                          style={{ fontSize: 11, color: "var(--c-success-text)" }}
                          onClick={() => setShowRaw(v => !v)}>
                          {showRaw ? "Hide raw" : "Show raw response"}
                        </button>
                      )}
                    </div>
                  )}

                  {/* Raw response preview */}
                  {showRaw && rawPreview && (
                    <div style={{
                      padding: "10px 12px", borderRadius: "var(--radius-sm)",
                      background: "#0f172a", color: "#e2e8f0",
                      fontFamily: "'SF Mono', 'Fira Code', monospace", fontSize: 11,
                      lineHeight: 1.6, overflowX: "auto", maxHeight: 200, overflowY: "auto",
                      whiteSpace: "pre-wrap", wordBreak: "break-all",
                    }}>
                      {rawPreview}
                    </div>
                  )}
                </div>

                {/* Capability list */}
                <div style={{ display: "flex", alignItems: "center",
                  justifyContent: "space-between", marginBottom: 4 }}>
                  <label className="form-label" style={{ marginBottom: 0 }}>
                    Capabilities
                    {form.capabilities.length > 0 && (
                      <span style={{ marginLeft: 8, fontSize: 12, fontWeight: 400,
                        color: "var(--text-muted)" }}>
                        {form.capabilities.length} defined
                      </span>
                    )}
                  </label>
                  <div style={{ display: "flex", gap: 8 }}>
                    {form.capabilities.length > 0 && (
                      <button type="button" className="btn btn-ghost btn-sm"
                        style={{ color: "var(--c-danger-text)", fontSize: 12 }}
                        onClick={() => {
                          if (window.confirm("Clear all capabilities?")) {
                            set("capabilities", []);
                            setFetchSuccess(false);
                          }
                        }}>
                        Clear all
                      </button>
                    )}
                    <button type="button" className="btn btn-secondary btn-sm" onClick={addCap}>
                      <IcPlus size={13} /> Add manually
                    </button>
                  </div>
                </div>

                {form.capabilities.length === 0
                  ? (
                  <div style={{
                    padding: "32px 24px", borderRadius: "var(--radius-sm)",
                    border: "1px dashed var(--border)", textAlign: "center",
                    color: "var(--text-muted)", fontSize: 14,
                  }}>
                    <div style={{ fontSize: 28, marginBottom: 8 }}>⚡</div>
                    <div style={{ fontWeight: 500, marginBottom: 4 }}>No capabilities defined</div>
                    <div style={{ fontSize: 13 }}>
                      Use "Auto-fetch capabilities" above, or add them manually.
                    </div>
                  </div>
                  ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {form.capabilities.map((cap, i) => (
                      <CapRow key={i} cap={cap}
                        onChange={v => updateCap(i, v)}
                        onRemove={() => removeCap(i)} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onCancel}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? <><Spinner /> Saving…</> : isEdit ? "Save changes" : "Register agent"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
