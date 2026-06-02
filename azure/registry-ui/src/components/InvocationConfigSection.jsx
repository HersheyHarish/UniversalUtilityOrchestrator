import React, { useState } from "react";
import { TooltipIcon } from "./Primitives.jsx";
import RequestSchemaEditor from "./RequestSchemaEditor.jsx";

const TIPS = {
  schema_mode: "Schema-driven: the LLM constructs the body at runtime from field descriptions. Template: use {token} placeholders. Default: sends task, session_id, customer_id, context.",
  response_result_path: "Dot-notation path to extract the result. e.g. result  or  data.text  or  choices.0.message.content. Blank = auto-detect.",
  extra_headers: "Non-auth static headers always sent. e.g. Accept: application/json",
  timeout_seconds: "Per-agent timeout in seconds. 0 = global default (AGENT_TIMEOUT_SECS).",
  max_retries: "Per-agent retries on network errors. -1 = global default (AGENT_MAX_RETRIES).",
  http_method: "HTTP method to invoke this agent. Almost always POST.",
  content_type: "Content-Type header for the invocation request.",
  body_template: "JSON body template with {token} placeholders. Tokens: {task}, {session_id}, {customer_id}, {context}, {step_N}. Leave empty to use defaults.",
};

export const DEFAULT_HEALTH = {
  check_type: "http",
  health_check_url: "",
  expected_http_status: 200,
  http_timeout_seconds: 10,
  tcp_port: 0,
  tcp_timeout_seconds: 5,
};

export const DEFAULT_INVOCATION = {
  request_schema: { fields: [], strict: true, json_schema: null },
  body_template: {},
  http_method: "POST",
  content_type: "application/json",
  response_result_path: "",
  extra_static_headers: {},
  timeout_seconds: 0,
  max_retries: -1,
};

const HC_TYPES = [
  { value: "http", label: "HTTP", desc: "GET health endpoint, check status code" },
  { value: "tcp", label: "TCP", desc: "Socket connect to host:port" },
  { value: "none", label: "None", desc: "Always healthy — no probe sent" },
];
const HC_COLORS = {
  http: { bg: "#e0f2fe", color: "#0369a1" },
  tcp: { bg: "#fef9c3", color: "#854d0e" },
  none: { bg: "#f1f5f9", color: "#334155" },
};

function Field({ label, tip, children }) {
  return (
    <div className="form-group">
      <label className="form-label" style={{ fontSize: 12 }}>
        {label} {tip && <TooltipIcon text={tip} />}
      </label>
      {children}
    </div>
  );
}

// ── Body template editor (unchanged from previous version) ────────────────────
function BodyTemplateEditor({ template, onChange }) {
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");
  const entries = Object.entries(template || {});

  const add = () => {
    if (!newKey.trim()) return;
    onChange({ ...(template || {}), [newKey.trim()]: newVal });
    setNewKey(""); setNewVal("");
  };
  const removeKey = (k) => {
    const next = { ...(template || {}) };
    delete next[k];
    onChange(next);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {entries.map(([k, v]) => (
        <div key={k} style={{
          display: "flex", gap: 8, alignItems: "center",
          padding: "6px 10px", borderRadius: "var(--radius-sm)",
          background: "var(--bg-page)", border: "1px solid var(--border)",
        }}>
          <code style={{ fontSize: 12, color: "var(--c-primary)", minWidth: 100, flexShrink: 0 }}>{k}</code>
          <span style={{ color: "var(--text-muted)", fontSize: 12 }}>→</span>
          <input className="form-control" value={typeof v === "string" ? v : JSON.stringify(v)}
            style={{ fontSize: 12, flex: 1 }}
            onChange={e => {
              let parsed;
              try { parsed = JSON.parse(e.target.value); } catch { parsed = e.target.value; }
              onChange({ ...(template || {}), [k]: parsed });
            }} />
          <button type="button" className="btn btn-ghost btn-sm btn-icon"
            style={{ color: "var(--c-danger)", flexShrink: 0 }}
            onClick={() => removeKey(k)}>×</button>
        </div>
      ))}
      <div style={{ display: "flex", gap: 8 }}>
        <input className="form-control" value={newKey} style={{ fontSize: 12, flex: "0 0 130px" }}
          placeholder="field name"
          onChange={e => setNewKey(e.target.value)}
          onKeyDown={e => e.key === "Enter" && add()} />
        <input className="form-control" value={newVal} style={{ fontSize: 12, flex: 1 }}
          placeholder='value or "{task}"'
          onChange={e => setNewVal(e.target.value)}
          onKeyDown={e => e.key === "Enter" && add()} />
        <button type="button" className="btn btn-secondary btn-sm" onClick={add}
          style={{ flexShrink: 0 }}>+ Add</button>
      </div>
      {entries.length === 0 && (
        <p className="form-hint">Empty = default schema (task, session_id, customer_id, context).</p>
      )}
    </div>
  );
}

// ── Static headers editor ─────────────────────────────────────────────────────
function StaticHeadersEditor({ headers, onChange }) {
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");
  const entries = Object.entries(headers || {});

  const add = () => {
    if (!newKey.trim()) return;
    onChange({ ...(headers || {}), [newKey.trim()]: newVal });
    setNewKey(""); setNewVal("");
  };
  const removeKey = (k) => {
    const next = { ...(headers || {}) };
    delete next[k];
    onChange(next);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {entries.map(([k, v]) => (
        <div key={k} style={{
          display: "flex", gap: 8, alignItems: "center",
          padding: "5px 10px", borderRadius: "var(--radius-sm)",
          background: "var(--bg-page)", border: "1px solid var(--border)",
        }}>
          <code style={{ fontSize: 12, color: "var(--text-secondary)", minWidth: 130, flexShrink: 0 }}>{k}</code>
          <span style={{ color: "var(--text-muted)", fontSize: 12 }}>:</span>
          <input className="form-control" value={v} style={{ fontSize: 12, flex: 1 }}
            onChange={e => onChange({ ...(headers || {}), [k]: e.target.value })} />
          <button type="button" className="btn btn-ghost btn-sm btn-icon"
            style={{ color: "var(--c-danger)", flexShrink: 0 }}
            onClick={() => removeKey(k)}>×</button>
        </div>
      ))}
      <div style={{ display: "flex", gap: 8 }}>
        <input className="form-control" value={newKey} style={{ fontSize: 12, flex: "0 0 180px" }}
          placeholder="Header-Name"
          onChange={e => setNewKey(e.target.value)}
          onKeyDown={e => e.key === "Enter" && add()} />
        <input className="form-control" value={newVal} style={{ fontSize: 12, flex: 1 }}
          placeholder="value"
          onChange={e => setNewVal(e.target.value)}
          onKeyDown={e => e.key === "Enter" && add()} />
        <button type="button" className="btn btn-secondary btn-sm" onClick={add}
          style={{ flexShrink: 0 }}>+ Add</button>
      </div>
    </div>
  );
}

// ── Health check section (unchanged) ─────────────────────────────────────────
export function HealthCheckSection({ config, onChange }) {
  const setC = (k, v) => onChange({ ...config, [k]: v });
  const check_type = config.check_type || "http";
  const { color } = HC_COLORS[check_type] || HC_COLORS.http;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="form-group">
        <label className="form-label">Health check type</label>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {HC_TYPES.map(t => {
            const selected = check_type === t.value;
            const { bg, color: tc } = HC_COLORS[t.value];
            return (
              <label key={t.value} style={{
                display: "flex", alignItems: "center", gap: 8, padding: "8px 14px",
                borderRadius: "var(--radius-sm)",
                border: `1px solid ${selected ? tc : "var(--border)"}`,
                background: selected ? bg : "var(--bg-card)",
                cursor: "pointer", transition: "all var(--transition)", flex: "0 0 auto",
              }}>
                <input type="radio" name="hc_type" value={t.value} checked={selected}
                  onChange={() => setC("check_type", t.value)} style={{ accentColor: tc }} />
                <div>
                  <div style={{
                    fontSize: 13, fontWeight: selected ? 600 : 400,
                    color: selected ? tc : "var(--text-primary)"
                  }}>{t.label}</div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{t.desc}</div>
                </div>
              </label>
            );
          })}
        </div>
      </div>

      {check_type === "http" && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 12, padding: 14,
          borderRadius: "var(--radius-sm)", background: "#e0f2fe22", border: "1px solid #bae6fd"
        }}>
          <Field label="Health check URL (optional)">
            <input className="form-control" value={config.health_check_url || ""}
              onChange={e => setC("health_check_url", e.target.value || null)}
              placeholder="Blank = auto-derived from endpoint URL" />
          </Field>
          <div className="grid-2">
            <Field label="Expected HTTP status">
              <input className="form-control" type="number" min="100" max="599"
                value={config.expected_http_status || 200}
                onChange={e => setC("expected_http_status", parseInt(e.target.value) || 200)} />
            </Field>
            <Field label="HTTP timeout (seconds)">
              <input className="form-control" type="number" min="1" max="60"
                value={config.http_timeout_seconds || 10}
                onChange={e => setC("http_timeout_seconds", parseInt(e.target.value) || 10)} />
            </Field>
          </div>
        </div>
      )}

      {check_type === "tcp" && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 12, padding: 14,
          borderRadius: "var(--radius-sm)", background: "#fef9c322", border: "1px solid #fde68a"
        }}>
          <div className="grid-2">
            <Field label="TCP port (0 = auto-detect)">
              <input className="form-control" type="number" min="0" max="65535"
                value={config.tcp_port || 0}
                onChange={e => setC("tcp_port", parseInt(e.target.value) || 0)} />
            </Field>
            <Field label="TCP timeout (seconds)">
              <input className="form-control" type="number" min="1" max="30"
                value={config.tcp_timeout_seconds || 5}
                onChange={e => setC("tcp_timeout_seconds", parseInt(e.target.value) || 5)} />
            </Field>
          </div>
        </div>
      )}

      {check_type === "none" && (
        <div className="alert alert-info" style={{ padding: "8px 12px", fontSize: 12 }}>
          Always treated as healthy — use for external services without a health endpoint.
        </div>
      )}
    </div>
  );
}

// ── Invocation section ─────────────────────────────────────────────────────────
export function InvocationSection({ config, onChange }) {
  const setC = (k, v) => onChange({ ...config, [k]: v });

  // Which body mode is active
  const hasSchemaFields = (config.request_schema?.fields || []).length > 0;
  const hasTemplate = Object.keys(config.body_template || {}).length > 0;
  const activeMode = hasSchemaFields ? "schema" : hasTemplate ? "template" : "default";

  const [bodyMode, setBodyMode] = useState(activeMode);

  const modeTabStyle = (mode) => ({
    padding: "6px 14px", fontSize: 12, fontWeight: bodyMode === mode ? 600 : 400,
    color: bodyMode === mode ? "var(--c-primary)" : "var(--text-secondary)",
    background: "none", border: "none",
    borderBottom: bodyMode === mode ? "2px solid var(--c-primary)" : "2px solid transparent",
    cursor: "pointer", transition: "all 0.15s",
  });

  const handleModeChange = (mode) => {
    setBodyMode(mode);
    // Clear the other mode's data when switching
    if (mode === "schema") {
      onChange({ ...config, body_template: {} });
    } else if (mode === "template") {
      onChange({ ...config, request_schema: { fields: [], strict: true, json_schema: null } });
    } else {
      onChange({
        ...config,
        request_schema: { fields: [], strict: true, json_schema: null },
        body_template: {},
      });
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* Transport settings (unchanged) */}
      <div className="grid-2">
        <Field label="HTTP method" tip={TIPS.http_method}>
          <select className="form-control" value={config.http_method || "POST"}
            onChange={e => setC("http_method", e.target.value)}>
            <option value="POST">POST</option>
            <option value="PUT">PUT</option>
            <option value="PATCH">PATCH</option>
            <option value="GET">GET</option>
          </select>
        </Field>
        <Field label="Content-Type" tip={TIPS.content_type}>
          <input className="form-control" value={config.content_type || "application/json"}
            onChange={e => setC("content_type", e.target.value)} />
        </Field>
      </div>

      {/* Body construction mode selector */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <label className="form-label" style={{ marginBottom: 0 }}>
            Body construction mode
          </label>
          <TooltipIcon text={TIPS.schema_mode} />
        </div>

        {/* Mode tabs */}
        <div style={{ display: "flex", borderBottom: "1px solid var(--border)", marginBottom: 14 }}>
          <button type="button" style={modeTabStyle("schema")} onClick={() => handleModeChange("schema")}>
            Schema-driven
            {bodyMode === "schema" && hasSchemaFields && (
              <span style={{
                marginLeft: 5, padding: "1px 5px", borderRadius: 99,
                fontSize: 10, fontWeight: 600,
                background: "var(--c-primary-light)", color: "var(--c-primary-text)"
              }}>
                {(config.request_schema?.fields || []).length} fields
              </span>
            )}
          </button>
          <button type="button" style={modeTabStyle("template")} onClick={() => handleModeChange("template")}>
            Template
          </button>
          <button type="button" style={modeTabStyle("default")} onClick={() => handleModeChange("default")}>
            Default
          </button>
        </div>

        {/* Schema-driven editor */}
        {bodyMode === "schema" && (
          <RequestSchemaEditor
            schema={config.request_schema || { fields: [], strict: true, json_schema: null }}
            onChange={v => setC("request_schema", v)}
          />
        )}

        {/* Template editor (legacy) */}
        {bodyMode === "template" && (
          <div>
            <div className="alert alert-info" style={{ padding: "8px 12px", fontSize: 12, marginBottom: 10 }}>
              Tokens: <code>{"{task}"}</code> <code>{"{session_id}"}</code>{" "}
              <code>{"{customer_id}"}</code> <code>{"{context}"}</code>{" "}
              <code>{"{step_N}"}</code>
            </div>
            <BodyTemplateEditor
              template={config.body_template || {}}
              onChange={v => setC("body_template", v)} />
          </div>
        )}

        {/* Default mode info */}
        {bodyMode === "default" && (
          <div style={{
            padding: "12px 14px", borderRadius: "var(--radius-sm)",
            background: "var(--bg-page)", border: "1px solid var(--border)",
            fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6
          }}>
            Default body schema:
            <pre style={{
              marginTop: 8, padding: "8px 12px", borderRadius: 6,
              background: "#0f172a", color: "#e2e8f0", fontSize: 11,
              fontFamily: "monospace", lineHeight: 1.6
            }}>
              {`{
  "task":        "<planner task>",
  "session_id":  "<session id>",
  "customer_id": "<customer id>",
  "context":     { "step_N_output": "..." }
}`}
            </pre>
          </div>
        )}
      </div>

      {/* Response & transport settings */}
      <Field label="Response result path" tip={TIPS.response_result_path}>
        <input className="form-control" value={config.response_result_path || ""}
          onChange={e => setC("response_result_path", e.target.value)}
          placeholder="e.g. result  or  data.text  or  choices.0.message.content" />
        <span className="form-hint">Blank = auto-detect from common keys.</span>
      </Field>

      <div className="form-group">
        <label className="form-label" style={{ marginBottom: 8 }}>
          Extra static headers (non-auth) <TooltipIcon text={TIPS.extra_headers} />
        </label>
        <StaticHeadersEditor
          headers={config.extra_static_headers || {}}
          onChange={v => setC("extra_static_headers", v)} />
      </div>

      <div className="grid-2">
        <Field label="Timeout (seconds)" tip={TIPS.timeout_seconds}>
          <input className="form-control" type="number" min="0"
            value={config.timeout_seconds || 0}
            onChange={e => setC("timeout_seconds", parseInt(e.target.value) || 0)}
            placeholder="0 = global default" />
        </Field>
        <Field label="Max retries" tip={TIPS.max_retries}>
          <input className="form-control" type="number" min="-1" max="5"
            value={config.max_retries ?? -1}
            onChange={e => setC("max_retries", parseInt(e.target.value))} />
          <span className="form-hint">-1 = global default</span>
        </Field>
      </div>
    </div>
  );
}