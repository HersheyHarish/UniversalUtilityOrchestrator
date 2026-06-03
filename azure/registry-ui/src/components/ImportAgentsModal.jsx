import React, { useMemo, useState, useRef } from "react";
import { agents as agentsApi } from "../api/client.js";
import { IcX, IcUpload, IcTrash } from "./Icons.jsx";
import { buildImportPayloads, parseImportJson } from "../utils/agentImport.js";

function AgentPreviewStrip({ agent }) {
  return (
    <div style={{
      padding: "10px 14px", borderRadius: "var(--radius-sm)",
      background: "var(--bg-page)", border: "1px solid var(--border)",
      display: "flex", flexDirection: "column", gap: 4,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{agent.name}</span>
        {agent.version && (
          <span className="badge badge-tag" style={{
            fontSize: 10, padding: "1px 6px",
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
      <div style={{ display: "flex", gap: 12, fontSize: 11, color: "var(--text-muted)", marginTop: 2, flexWrap: "wrap" }}>
        {agent.endpoint_url && (
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 280 }} title={agent.endpoint_url}>
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

export default function ImportAgentsModal({ onCancel, onImported }) {
  const fileInputRef = useRef(null);
  const [fileName, setFileName] = useState("");
  const [rawJson, setRawJson] = useState("");
  const [parsingError, setParsingError] = useState("");
  const [importErrors, setImportErrors] = useState([]);
  const [isImporting, setIsImporting] = useState(false);
  const [results, setResults] = useState([]);

  const parsed = useMemo(() => {
    if (!rawJson.trim()) return null;
    try {
      const parsedJson = parseImportJson(rawJson);
      const transformed = buildImportPayloads(parsedJson);
      setParsingError("");
      return transformed;
    } catch (err) {
      setParsingError(err.message);
      return null;
    }
  }, [rawJson]);

  // ── File Selection ──
  const handleFileSelect = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setFileName(file.name);
    setParsingError("");
    setResults([]);
    setImportErrors([]);

    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target.result;
      setRawJson(text);
    };
    reader.onerror = () => {
      setParsingError("Could not read file.");
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const clearFile = () => {
    setFileName("");
    setRawJson("");
    setResults([]);
    setParsingError("");
    setImportErrors([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // ── Manual Text Area Changes ──
  const handleTextChange = (e) => {
    setRawJson(e.target.value);
    setResults([]);
    setImportErrors([]);
  };

  async function handleImport() {
    if (!parsed) return;
    setImportErrors([]);
    setResults([]);
    setIsImporting(true);
    try {
      if (parsed.errors.length) {
        setImportErrors(parsed.errors);
      }
      const successfulPayloads = parsed.payloads;
      if (successfulPayloads.length === 0) return;

      const upsertResults = await agentsApi.importReplaceByName(successfulPayloads);
      setResults(upsertResults);
      const created = upsertResults.filter((r) => r.ok && r.action === "created").length;
      const updated = upsertResults.filter((r) => r.ok && r.action === "updated").length;
      onImported?.(created + updated); // Fix toast bug by returning the successful integer count
    } catch (err) {
      setParsingError(err.message || "Import failed.");
    } finally {
      setIsImporting(false);
    }
  }

  const canImport = parsed && parsed.payloads.length > 0 && !isImporting && !parsingError;
  const hasResults = results.length > 0;

  return (
    <div className="modal-backdrop" onClick={!isImporting ? onCancel : undefined}>
      <div className="modal import-modal" style={{ maxWidth: 640 }} onClick={(e) => e.stopPropagation()}>
        
        {/* Header */}
        <div className="modal-header">
          <div>
            <div className="modal-title">Import agents</div>
            <div className="text-sm text-muted" style={{ marginTop: 3 }}>
              Select a JSON file or paste agent JSON directly.
            </div>
          </div>
          <button className="btn btn-ghost btn-icon" onClick={onCancel} disabled={isImporting} aria-label="Close import modal">
            <IcX size={16} />
          </button>
        </div>

        <div className="modal-body" style={{ maxHeight: "calc(100vh - 200px)", overflowY: "auto" }}>
          
          {/* File Picker */}
          <div className="form-group">
            <label className="form-label">Source file</label>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <input
                ref={fileInputRef}
                type="file"
                accept=".json,application/json"
                style={{ display: "none" }}
                onChange={handleFileSelect}
                disabled={isImporting}
              />
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => fileInputRef.current?.click()}
                disabled={isImporting}
              >
                <IcUpload size={14} /> Select JSON file
              </button>
              {fileName ? (
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
                    onClick={clearFile} title="Clear" disabled={isImporting}>
                    <IcTrash size={13} />
                  </button>
                </div>
              ) : (
                <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
                  No file selected
                </span>
              )}
            </div>
            <span className="form-hint">
              Accepts core agents array or registry export format.
            </span>
          </div>

          {/* Divider */}
          <div style={{
            display: "flex", alignItems: "center", gap: 12,
            color: "var(--text-muted)", fontSize: 12, margin: "16px 0"
          }}>
            <div style={{ flex: 1, height: 1, background: "var(--border)" }} />
            or paste / edit JSON below
            <div style={{ flex: 1, height: 1, background: "var(--border)" }} />
          </div>

          {/* Text Area */}
          <div className="form-group">
            <label className="form-label">Agents JSON</label>
            <textarea
              className="form-control import-textarea"
              placeholder='{"agents":[{"name":"billing_agent","description":"...","endpoint":"http://localhost:8001/billing_agent/api","capabilities":["..."]}]}'
              value={rawJson}
              onChange={handleTextChange}
              disabled={isImporting}
              rows={8}
              style={{
                fontFamily: "'SF Mono', 'Fira Code', monospace",
                fontSize: 12, lineHeight: 1.5, resize: "vertical"
              }}
            />
          </div>

          {parsingError && <div className="alert alert-error">{parsingError}</div>}

          {/* Transformed Preview list */}
          {parsed && !parsingError && !hasResults && (
            <div className="form-group" style={{ marginTop: 16 }}>
              <label className="form-label">
                Preview ({parsed.payloads.length} agent{parsed.payloads.length !== 1 ? "s" : ""} detected)
              </label>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 220, overflowY: "auto", padding: "2px" }}>
                {parsed.payloads.map((agent, i) => (
                  <AgentPreviewStrip key={i} agent={agent} />
                ))}
              </div>
            </div>
          )}

          {/* Validation Issues */}
          {importErrors.length > 0 && (
            <div className="import-results" style={{ marginTop: 16 }}>
              <div className="text-sm" style={{ fontWeight: 600, color: "var(--c-danger-text)", marginBottom: 8 }}>
                Validation issues
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {importErrors.map((err, i) => (
                  <div key={i} className="import-result-row failed" style={{
                    padding: "6px 10px", borderRadius: "var(--radius-sm)",
                    background: "#fff5f5", border: "1px solid #fca5a5",
                    fontSize: 13, color: "#991b1b"
                  }}>{err}</div>
                ))}
              </div>
            </div>
          )}

          {/* Import Results */}
          {hasResults && (
            <div className="import-results" style={{ marginTop: 16 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 8 }}>
                Import results
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {results.map((r, i) => (
                  <div key={i} className={`import-result-row ${r.ok ? "ok" : "failed"}`} style={{
                    display: "flex", alignItems: "center", justifySpace: "between", gap: 10,
                    padding: "8px 12px", borderRadius: "var(--radius-sm)",
                    background: r.ok ? "#f0fdf4" : "#fff5f5",
                    border: `1px solid ${r.ok ? "#bbf7d0" : "#fca5a5"}`,
                    fontSize: 13
                  }}>
                    <span style={{ fontWeight: 600, flex: 1 }}>{r.name}</span>
                    <span style={{
                      fontWeight: 500,
                      color: r.ok ? "#15803d" : "#991b1b",
                      textTransform: "capitalize"
                    }}>{r.ok ? r.action : r.error}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onCancel} disabled={isImporting}>
            {hasResults ? "Close" : "Cancel"}
          </button>
          {!hasResults && (
            <button className="btn btn-primary" onClick={handleImport} disabled={!canImport}>
              {isImporting ? "Importing..." : parsed && parsed.payloads.length > 1 ? `Import ${parsed.payloads.length} agents` : "Import agents"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
