import React, { useMemo, useState } from "react";
import { agents as agentsApi } from "../api/client.js";
import { IcX } from "./Icons.jsx";
import { buildImportPayloads, parseImportJson } from "../utils/agentImport.js";

export default function ImportAgentsModal({ onCancel, onImported }) {
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
      const failed = upsertResults.filter((r) => !r.ok).length + parsed.errors.length;
      onImported?.({ created, updated, failed });
    } finally {
      setIsImporting(false);
    }
  }

  const previewNames = parsed?.payloads?.map((p) => p.name) || [];
  const disabled = isImporting || !parsed || (parsed.payloads.length === 0 && parsed.errors.length > 0);

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal import-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <div className="modal-title">Import agents JSON</div>
            <div className="text-sm text-muted">Paste content matching src/core/agents.json shape.</div>
          </div>
          <button className="btn btn-ghost btn-icon" onClick={onCancel} aria-label="Close import modal">
            <IcX size={16} />
          </button>
        </div>
        <div className="modal-body">
          <div className="form-group">
            <label className="form-label">Agents JSON</label>
            <textarea
              className="form-control import-textarea"
              placeholder='{"agents":[{"name":"billing_agent","description":"...","endpoint":"http://localhost:8001/billing_agent/api","capabilities":["..."]}]}'
              value={rawJson}
              onChange={(e) => setRawJson(e.target.value)}
            />
          </div>

          {parsingError && <div className="alert alert-error">{parsingError}</div>}

          {parsed && !parsingError && (
            <div className="alert alert-info">
              Ready to import {parsed.payloads.length} agent{parsed.payloads.length !== 1 ? "s" : ""}.
              Existing names will be replaced.
            </div>
          )}

          {previewNames.length > 0 && (
            <div className="import-preview">
              <div className="text-sm" style={{ fontWeight: 600 }}>Preview</div>
              <div className="tag-list">
                {previewNames.map((name) => (
                  <span key={name} className="badge badge-tag">{name}</span>
                ))}
              </div>
            </div>
          )}

          {importErrors.length > 0 && (
            <div className="import-results">
              <div className="text-sm" style={{ fontWeight: 600 }}>Validation issues</div>
              {importErrors.map((err) => (
                <div key={err} className="import-result-row failed">{err}</div>
              ))}
            </div>
          )}

          {results.length > 0 && (
            <div className="import-results">
              <div className="text-sm" style={{ fontWeight: 600 }}>Import results</div>
              {results.map((r) => (
                <div key={`${r.name}-${r.action}`} className={`import-result-row ${r.ok ? "ok" : "failed"}`}>
                  <span>{r.name}</span>
                  <span>{r.ok ? r.action : r.error}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onCancel} disabled={isImporting}>Cancel</button>
          <button className="btn btn-primary" onClick={handleImport} disabled={disabled}>
            {isImporting ? "Importing..." : "Import agents"}
          </button>
        </div>
      </div>
    </div>
  );
}
