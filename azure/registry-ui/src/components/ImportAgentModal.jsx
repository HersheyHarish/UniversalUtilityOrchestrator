import React, { useRef, useState } from "react";
import { agents as agentsApi } from "../api/client.js";
import { Spinner, Alert } from "./Primitives.jsx";
import { IcUpload, IcTrash } from "./Icons.jsx";

const AGENT_CREATE_FIELDS = new Set([
  "name", "description", "endpoint_url", "api_key_secret_name",
  "status", "version", "utility_types", "tags", "capabilities", "metadata",
  "invocation_config", "auth_config", "health_check_config",
]);

function toAgentCreate(raw) {
  const out = {};
  for (const key of AGENT_CREATE_FIELDS) {
    if (key in raw) out[key] = raw[key];
  }
  return out;
}

function parseInput(text) {
  if (!text.trim()) return { agents: [], error: null };

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    return { agents: [], error: `Invalid JSON: ${e.message}` };
  }

  if (parsed && typeof parsed === "object" && !Array.isArray(parsed) && Array.isArray(parsed.agents)) {
    parsed = parsed.agents;
  }

  const list = Array.isArray(parsed) ? parsed : [parsed];

  for (const entry of list) {
    if (!entry || typeof entry !== "object") {
      return { agents: [], error: "Each entry must be a JSON object." };
    }
    if (!entry.name) {
      return { agents: [], error: `Missing required field "name" in one or more agents.` };
    }
  }

  return { agents: list, error: null };
}

// ── Preview strip ─────────────────────────────────────────────────────────────

function AgentPreviewStrip({ agent }) {
  return (
    <div style={{
      padding: "10px 14px", borderRadius: "var(--radius-sm)",
      background: "var(--bg-page)", border: "1px solid var(--border)",
      display: "flex", flexDirection: "column", gap: 4,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>{agent.name}</span>
        {agent.version && (
          <span style={{
            fontSize: 11, fontWeight: 500,
            background: "var(--c-primary-light)", color: "var(--c-primary-text)",
            padding: "1px 7px", borderRadius: 99,
          }}>v{agent.version}</span>
        )}
      </div>
      {agent.description && (
        <div style={{
          fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5,
          overflow: "hidden", textOverflow: "ellipsis",
          display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
        }}>
          {agent.description}
        </div>
      )}
      <div style={{ display: "flex", gap: 12, fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
        {agent.endpoint_url && (
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 280 }}>
            🔗 {agent.endpoint_url}
          </span>
        )}
        {agent.capabilities?.length > 0 && (
          <span>⚡ {agent.capabilities.length} capability{agent.capabilities.length !== 1 ? "ies" : "y"}</span>
        )}
        {agent.utility_types?.length > 0 && (
          <span>🔌 {agent.utility_types.join(", ")}</span>
        )}
      </div>
    </div>
  );
}

// ── Result row (shown after import attempt) ───────────────────────────────────

function ResultRow({ name, ok, message }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "6px 10px", borderRadius: "var(--radius-sm)",
      background: ok ? "#f0fdf4" : "#fff5f5",
      border: `1px solid ${ok ? "#bbf7d0" : "#fca5a5"}`,
    }}>
      <span style={{ fontSize: 16, flexShrink: 0 }}>{ok ? "✓" : "✕"}</span>
      <span style={{ fontSize: 13, fontWeight: 600, flex: 1 }}>{name}</span>
      {message && (
        <span style={{ fontSize: 12, color: ok ? "#15803d" : "#991b1b" }}>{message}</span>
      )}
    </div>
  );
}

// ── Main modal ────────────────────────────────────────────────────────────────

export default function ImportAgentModal({ onImported, onCancel }) {
  const fileInputRef = useRef(null);

  const [fileName, setFileName] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [parseResult, setParseResult] = useState({ agents: [], error: null });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [results, setResults] = useState(null);  // null = not run yet

  // ── File selection ─────────────────────────────────────────────────────────
  const handleFileSelect = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setFileName(file.name);
    setResults(null);
    setError("");

    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target.result;
      setJsonText(text);
      setParseResult(parseInput(text));
    };
    reader.onerror = () => {
      setError("Could not read file.");
    };
    reader.readAsText(file);

    // Reset input so selecting the same file again triggers onChange
    e.target.value = "";
  };

  // ── Manual textarea edit ───────────────────────────────────────────────────
  const handleTextChange = (e) => {
    const text = e.target.value;
    setJsonText(text);
    setParseResult(parseInput(text));
    setResults(null);
    setError("");
  };

  const clearFile = () => {
    setFileName("");
    setJsonText("");
    setParseResult({ agents: [], error: null });
    setResults(null);
    setError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // ── Import ─────────────────────────────────────────────────────────────────
  const handleImport = async () => {
    const { agents, error: parseErr } = parseResult;
    if (parseErr) { setError(parseErr); return; }
    if (!agents.length) { setError("No agent data to import."); return; }

    setLoading(true);
    setError("");

    const resultList = [];
    let anyOk = false;

    for (const raw of agents) {
      const payload = toAgentCreate(raw);
      try {
        await agentsApi.create(payload);
        resultList.push({ name: payload.name || raw.name, ok: true, message: "Registered" });
        anyOk = true;
      } catch (err) {
        resultList.push({ name: payload.name || raw.name, ok: false, message: err.message });
      }
    }

    setResults(resultList);
    setLoading(false);

    if (anyOk) {
      onImported(resultList.filter(r => r.ok).length);
    }
  };

  // ── Derived state ──────────────────────────────────────────────────────────
  const { agents, error: parseErr } = parseResult;
  const canImport = agents.length > 0 && !parseErr && !loading;
  const hasResults = results !== null;

  // ── Status line below the textarea ────────────────────────────────────────
  let statusLine = null;
  if (jsonText.trim()) {
    if (parseErr) {
      statusLine = (
        <div style={{
          fontSize: 12, color: "var(--c-danger-text)",
          display: "flex", alignItems: "center", gap: 4
        }}>
          <span>✕</span> {parseErr}
        </div>
      );
    } else if (agents.length > 0) {
      statusLine = (
        <div style={{
          fontSize: 12, color: "#15803d",
          display: "flex", alignItems: "center", gap: 4
        }}>
          <span>✓</span> Valid JSON ·{" "}
          <strong>{agents.length}</strong>{" "}
          agent{agents.length !== 1 ? "s" : ""} detected
        </div>
      );
    }
  }

  return (
    <div className="modal-backdrop" onClick={!loading ? onCancel : undefined}>
      <div className="modal" style={{ maxWidth: 620 }} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="modal-header">
          <div>
            <div className="modal-title">Import agent</div>
            <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 3 }}>
              Select a JSON file or paste agent JSON directly
            </div>
          </div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onCancel}
            disabled={loading}>×</button>
        </div>

        <div className="modal-body">
          {error && <Alert type="error" onClose={() => setError("")}>{error}</Alert>}

          {/* ── File picker ── */}
          <div className="form-group">
            <label className="form-label">Source file</label>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <input
                ref={fileInputRef}
                type="file"
                accept=".json,application/json"
                style={{ display: "none" }}
                onChange={handleFileSelect}
              />
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => fileInputRef.current?.click()}
                disabled={loading}
              >
                <IcUpload size={14} /> Select JSON file
              </button>
              {fileName
                ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0 }}>
                    <span style={{
                      fontSize: 13, color: "var(--text-primary)",
                      fontWeight: 500, overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      📄 {fileName}
                    </span>
                    <button type="button" className="btn btn-ghost btn-icon btn-sm"
                      style={{ color: "var(--text-muted)", flexShrink: 0 }}
                      onClick={clearFile} title="Clear">
                      <IcTrash size={13} />
                    </button>
                  </div>
                )
                : (
                  <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
                    No file selected
                  </span>
                )
              }
            </div>
            <span className="form-hint">
              Accepts single agent JSON or the export format from another registry
              (single object, array, or <code style={{ fontSize: 11 }}>{`{ "agents": [...] }`}</code>).
            </span>
          </div>

          {/* ── Divider ── */}
          <div style={{
            display: "flex", alignItems: "center", gap: 12,
            color: "var(--text-muted)", fontSize: 12,
          }}>
            <div style={{ flex: 1, height: 1, background: "var(--border)" }} />
            or paste / edit JSON below
            <div style={{ flex: 1, height: 1, background: "var(--border)" }} />
          </div>

          {/* ── JSON textarea ── */}
          <div className="form-group">
            <label className="form-label">
              Agent JSON
              {agents.length > 0 && !parseErr && (
                <span style={{
                  marginLeft: 8, fontSize: 11, fontWeight: 400,
                  color: "var(--text-muted)"
                }}>
                  — editable before import
                </span>
              )}
            </label>
            <textarea
              className={`form-control ${parseErr && jsonText.trim() ? "error" : ""}`}
              value={jsonText}
              onChange={handleTextChange}
              placeholder={`Paste agent JSON here, e.g.\n{\n  "name": "BillingAgent",\n  "description": "Handles billing queries",\n  "endpoint_url": "https://fn-billing.azurewebsites.net/api/invoke"\n}`}
              rows={10}
              style={{
                fontFamily: "'SF Mono', 'Fira Code', 'Courier New', monospace",
                fontSize: 12, lineHeight: 1.6, resize: "vertical",
              }}
              disabled={loading}
            />
            {statusLine && <div style={{ marginTop: 4 }}>{statusLine}</div>}
          </div>

          {/* ── Agent preview (before import) ── */}
          {agents.length > 0 && !parseErr && !hasResults && (
            <div className="form-group">
              <label className="form-label">
                Preview
                {agents.length > 1 && (
                  <span style={{
                    marginLeft: 6, fontSize: 11, fontWeight: 400,
                    color: "var(--text-muted)"
                  }}>
                    ({agents.length} agents will be imported)
                  </span>
                )}
              </label>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {agents.slice(0, 5).map((a, i) => (
                  <AgentPreviewStrip key={i} agent={a} />
                ))}
                {agents.length > 5 && (
                  <div style={{
                    fontSize: 12, color: "var(--text-muted)",
                    textAlign: "center", padding: "4px 0"
                  }}>
                    + {agents.length - 5} more…
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Import results ── */}
          {hasResults && (
            <div className="form-group">
              <label className="form-label">Import results</label>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {results.map((r, i) => (
                  <ResultRow key={i} name={r.name} ok={r.ok} message={r.message} />
                ))}
              </div>
              {results.some(r => !r.ok) && (
                <span className="form-hint" style={{ marginTop: 6 }}>
                  Failed agents may already exist (duplicate name) or have validation errors.
                  Fix the JSON and retry.
                </span>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="modal-footer">
          <button type="button" className="btn btn-secondary"
            onClick={onCancel} disabled={loading}>
            {hasResults ? "Close" : "Cancel"}
          </button>
          {!hasResults && (
            <button type="button" className="btn btn-primary"
              onClick={handleImport} disabled={!canImport}>
              {loading
                ? <><Spinner /> Importing…</>
                : agents.length > 1
                  ? `Import ${agents.length} agents`
                  : "Import agent"
              }
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
