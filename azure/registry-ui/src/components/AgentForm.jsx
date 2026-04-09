import React, { useState } from "react";
import { agents as agentsApi } from "../api/client.js";
import { Spinner, Alert, TooltipIcon } from "./Primitives.jsx";
import { IcPlus, IcTrash } from "./Icons.jsx";
import AuthConfigSection, {
  DEFAULT_AUTH_CONFIG,
  DEFAULT_AUTH_SECRETS,
} from "./AuthConfigSection.jsx";

const UTILITY_TYPES = ["electric", "gas", "water", "multi"];

const TIPS = {
  name:    "Unique identifier. PascalCase, no spaces. e.g. BillingAgent.",
  desc:    "Sent verbatim to the planner LLM. Be specific about what this agent handles.",
  url:     "Full HTTPS invoke URL. e.g. https://fn-billing-ua001.azurewebsites.net/api/invoke",
  version: "Semantic version. e.g. 1.2.0",
  types:   "Which utility commodities this agent handles.",
  tags:    "Comma-separated labels for filtering. e.g. billing, payments",
  capName: "snake_case identifier. e.g. explain_bill",
  capDesc: "What this capability does. One sentence.",
};

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

  const [authConfig,  setAuthConfig]  = useState(
    initial?.auth_config
      ? { ...DEFAULT_AUTH_CONFIG, ...initial.auth_config }
      : { ...DEFAULT_AUTH_CONFIG }
  );
  const [authSecrets, setAuthSecrets] = useState({ ...DEFAULT_AUTH_SECRETS });

  const [error,     setError]    = useState("");
  const [loading,   setLoading]  = useState(false);
  const [activeTab, setActiveTab] = useState("basic");

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

  // Has any secret value been entered?
  const hasSecrets = Boolean(
    authSecrets.api_key_value ||
    authSecrets.bearer_token_value ||
    authSecrets.basic_auth_password_value ||
    authSecrets.oauth2_client_secret_value ||
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
      tags:         form.tags.split(",").map(t => t.trim()).filter(Boolean),
      capabilities: form.capabilities.filter(c => c.name.trim()),
      auth_config:  authConfig,
      // Only send auth_secrets if values were actually entered
      auth_secrets: hasSecrets ? authSecrets : null,
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

  const tabStyle = (tab) => ({
    padding: "8px 16px", fontSize: 13,
    fontWeight: activeTab === tab ? 600 : 400,
    color: activeTab === tab ? "var(--c-primary)" : "var(--text-secondary)",
    background: "none", border: "none",
    borderBottom: activeTab === tab
      ? "2px solid var(--c-primary)"
      : "2px solid transparent",
    cursor: "pointer", transition: "all var(--transition)",
  });

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" style={{ maxWidth: 700 }} onClick={e => e.stopPropagation()}>

        <div className="modal-header">
          <div>
            <div className="modal-title">
              {isEdit ? `Edit — ${initial.name}` : "Register new agent"}
            </div>
            <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 3 }}>
              {isEdit ? "Update agent configuration" : "Add a remote agent to the registry"}
            </div>
          </div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onCancel}>×</button>
        </div>

        {/* Tab bar */}
        <div style={{
          display: "flex", borderBottom: "1px solid var(--border)",
          padding: "0 24px", gap: 4,
        }}>
          <button style={tabStyle("basic")} onClick={() => setActiveTab("basic")}>
            Basic info
          </button>
          <button style={tabStyle("auth")} onClick={() => setActiveTab("auth")}>
            Auth config
            {authConfig.auth_type !== "none" && (
              <span style={{
                marginLeft: 6, padding: "1px 6px", borderRadius: 99,
                fontSize: 10, fontWeight: 600,
                background: "var(--c-primary-light)", color: "var(--c-primary-text)",
              }}>
                {authConfig.auth_type}
              </span>
            )}
          </button>
          <button style={tabStyle("capabilities")} onClick={() => setActiveTab("capabilities")}>
            Capabilities
            {form.capabilities.length > 0 && (
              <span style={{
                marginLeft: 6, padding: "1px 6px", borderRadius: 99,
                fontSize: 10, fontWeight: 600,
                background: "var(--c-neutral-bg)", color: "var(--c-neutral-text)",
              }}>
                {form.capabilities.length}
              </span>
            )}
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {error && <Alert type="error" onClose={() => setError("")}>{error}</Alert>}

            {/* Basic tab */}
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
                    {isEdit && (
                      <span className="form-hint">Name cannot be changed after creation.</span>
                    )}
                  </div>
                  <div className="form-group">
                    <label className="form-label">
                      Version <TooltipIcon text={TIPS.version} />
                    </label>
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
                    placeholder="What does this agent do? Be specific — sent to the planner LLM." />
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
                  <label className="form-label">
                    Utility types <TooltipIcon text={TIPS.types} />
                  </label>
                  <div className="filter-chips">
                    {UTILITY_TYPES.map(t => (
                      <span key={t}
                        className={`chip ${form.utility_types.includes(t) ? "selected" : ""}`}
                        onClick={() => setU(t)}>
                        {t}
                      </span>
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

            {/* Auth tab */}
            {activeTab === "auth" && (
              <AuthConfigSection
                config={authConfig}
                secrets={authSecrets}
                onChangeConfig={setAuthConfig}
                onChangeSecrets={setAuthSecrets}
              />
            )}

            {/* Capabilities tab */}
            {activeTab === "capabilities" && (
              <div className="form-group">
                <div style={{
                  display: "flex", alignItems: "center",
                  justifyContent: "space-between", marginBottom: 12,
                }}>
                  <label className="form-label" style={{ marginBottom: 0 }}>
                    Capabilities
                  </label>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={addCap}>
                    <IcPlus size={13} /> Add capability
                  </button>
                </div>
                {form.capabilities.length === 0
                  ? (
                  <p style={{ fontSize: 13, color: "var(--text-muted)", fontStyle: "italic" }}>
                    No capabilities yet. Add at least one so the planner knows what this agent can do.
                  </p>
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
              {loading
                ? <><Spinner /> Saving…</>
                : isEdit ? "Save changes" : "Register agent"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
