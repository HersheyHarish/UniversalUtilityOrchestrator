import React, { useState } from "react";
import { TooltipIcon } from "./Primitives.jsx";

// ── Auth type definitions ─────────────────────────────────────────────────────

const AUTH_TYPES = [
  { value: "none",         label: "No auth",      desc: "No authentication headers or params added" },
  { value: "api_key",      label: "API key",       desc: "Inject a key into a header or query param" },
  { value: "bearer_token", label: "Bearer token",  desc: "Authorization: Bearer <token>" },
  { value: "basic_auth",   label: "Basic auth",    desc: "Authorization: Basic <base64(user:pass)>" },
  { value: "oauth2",       label: "OAuth2",        desc: "Client credentials grant — auto-fetches & caches token" },
  { value: "custom",       label: "Custom",        desc: "Arbitrary header / query-param injection" },
];

export const AUTH_COLORS = {
  none:         { bg: "#f1f5f9", color: "#334155" },
  api_key:      { bg: "#e0e7ff", color: "#3730a3" },
  bearer_token: { bg: "#dcfce7", color: "#15803d" },
  basic_auth:   { bg: "#fef3c7", color: "#92400e" },
  oauth2:       { bg: "#ede9fe", color: "#5b21b6" },
  custom:       { bg: "#fce7f3", color: "#9d174d" },
};

const TIPS = {
  api_key_location:    "Header: sent as a request header (most common). Query param: appended to the URL.",
  api_key_name:        "Header or query param name. e.g. x-api-key, x-functions-key, Authorization.",
  api_key_value:       "The actual API key value. The backend stores this in Azure Key Vault — it is never saved in the database.",
  bearer_token_value:  "The bearer token (without the 'Bearer ' prefix). Stored in Key Vault by the backend.",
  basic_username:      "The username for Basic auth. Not sensitive — stored directly in the registry.",
  basic_password:      "The password for Basic auth. Stored in Key Vault by the backend.",
  oauth2_token_url:    "The token endpoint URL. e.g. https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
  oauth2_client_id:    "The OAuth2 client ID (application ID). Not sensitive — stored in the registry.",
  oauth2_client_secret:"The OAuth2 client secret. Stored in Key Vault by the backend.",
  oauth2_scopes:       "Space-separated scopes. e.g. https://service.azure.com/.default — leave blank if not required.",
  oauth2_ttl:          "How long to cache the access token in seconds (default 3600 = 1 hour). The orchestrator fetches a new token this many seconds before expiry.",
  custom_key:          "Header name or query param name to inject. e.g. X-Tenant-Id, tenant_id.",
  custom_inject_as:    "Header: added to HTTP headers. Query param: appended to the URL.",
  custom_value:        "Plain text value for non-sensitive data (e.g. tenant IDs, flags). Stored directly in the registry.",
  custom_secret:       "Sensitive value stored in Key Vault by the backend. Leave the plain value blank when using this.",
};

// ── Badge ─────────────────────────────────────────────────────────────────────

export function AuthTypeBadge({ authType }) {
  const { bg, color } = AUTH_COLORS[authType] || AUTH_COLORS.none;
  const label = AUTH_TYPES.find(t => t.value === authType)?.label || authType || "none";
  return (
    <span style={{
      background: bg, color,
      padding: "3px 10px", borderRadius: 99,
      fontSize: 12, fontWeight: 500, whiteSpace: "nowrap",
    }}>
      {label}
    </span>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function Field({ label, tip, required, children }) {
  return (
    <div className="form-group">
      <label className="form-label" style={{ fontSize: 12 }}>
        {label}
        {required && <span className="form-required"> *</span>}
        {tip && <TooltipIcon text={tip} />}
      </label>
      {children}
    </div>
  );
}

function PasswordInput({ value, onChange, placeholder, hasExistingSecret }) {
  const [show, setShow] = useState(false);
  return (
    <div style={{ position: "relative" }}>
      <input
        className="form-control"
        type={show ? "text" : "password"}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={hasExistingSecret ? "••••••  (leave blank to keep existing)" : placeholder}
        style={{ paddingRight: 44 }}
        autoComplete="new-password"
      />
      <button
        type="button"
        onClick={() => setShow(s => !s)}
        style={{
          position: "absolute", right: 10, top: "50%",
          transform: "translateY(-50%)",
          background: "none", border: "none", cursor: "pointer",
          fontSize: 12, color: "var(--text-muted)", padding: "2px 4px",
        }}
      >
        {show ? "hide" : "show"}
      </button>
    </div>
  );
}

function SecretHint({ secretName }) {
  if (!secretName) return null;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6,
      marginTop: 4, fontSize: 11, color: "var(--text-muted)",
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%",
        background: "var(--c-success)", display: "inline-block",
      }} />
      Secret stored in Key Vault as <code style={{ fontSize: 10 }}>{secretName}</code>
    </div>
  );
}

// ── Custom entry row ──────────────────────────────────────────────────────────

function CustomEntryRow({ entry, secret, onChangeEntry, onChangeSecret, onRemove }) {
  return (
    <div style={{
      padding: "12px 14px", borderRadius: "var(--radius-sm)",
      background: "var(--bg-page)", border: "1px solid var(--border)",
      display: "flex", flexDirection: "column", gap: 10,
    }}>
      <div className="grid-2">
        <Field label="Key name" tip={TIPS.custom_key}>
          <input className="form-control" value={entry.key || ""} style={{ fontSize: 13 }}
            placeholder="e.g. X-Tenant-Id"
            onChange={e => onChangeEntry({ ...entry, key: e.target.value })} />
        </Field>
        <Field label="Inject as" tip={TIPS.custom_inject_as}>
          <select className="form-control" value={entry.inject_as || "header"} style={{ fontSize: 13 }}
            onChange={e => onChangeEntry({ ...entry, inject_as: e.target.value })}>
            <option value="header">Header</option>
            <option value="query_param">Query param</option>
          </select>
        </Field>
      </div>
      <div className="grid-2">
        <Field label="Plain value (non-sensitive)" tip={TIPS.custom_value}>
          <input className="form-control" value={entry.value || ""} style={{ fontSize: 13 }}
            placeholder="e.g. tenant-001"
            onChange={e => onChangeEntry({ ...entry, value: e.target.value || null })} />
        </Field>
        <Field label="Secret value (sensitive → Key Vault)" tip={TIPS.custom_secret}>
          <PasswordInput
            value={secret || ""}
            onChange={v => onChangeSecret(v || null)}
            placeholder="Stored in Key Vault"
            hasExistingSecret={Boolean(entry.secret_name)}
          />
          <SecretHint secretName={entry.secret_name} />
        </Field>
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button type="button" className="btn btn-danger btn-sm" onClick={onRemove}>
          Remove entry
        </button>
      </div>
    </div>
  );
}

// ── DEFAULT CONFIG ─────────────────────────────────────────────────────────────

export const DEFAULT_AUTH_CONFIG = {
  auth_type: "none",
  api_key_location: "header",
  api_key_name: "",
  api_key_secret_name: null,
  bearer_token_secret_name: null,
  basic_auth_username: "",
  basic_auth_password_secret_name: null,
  oauth2_token_url: "",
  oauth2_client_id: "",
  oauth2_client_secret_name: null,
  oauth2_scopes: "",
  oauth2_token_ttl_seconds: 3600,
  custom_entries: [],
};

export const DEFAULT_AUTH_SECRETS = {
  api_key_value: "",
  bearer_token_value: "",
  basic_auth_password_value: "",
  oauth2_client_secret_value: "",
  custom_secret_values: [],
};

// ── Main component ────────────────────────────────────────────────────────────

export default function AuthConfigSection({ config, secrets, onChangeConfig, onChangeSecrets }) {
  const auth_type = config?.auth_type || "none";

  const setC = (key, val) => onChangeConfig({ ...config, [key]: val });
  const setS = (key, val) => onChangeSecrets({ ...secrets, [key]: val });

  const addEntry = () => {
    onChangeConfig({
      ...config,
      custom_entries: [
        ...(config.custom_entries || []),
        { key: "", inject_as: "header", value: null, secret_name: null },
      ],
    });
    onChangeSecrets({
      ...secrets,
      custom_secret_values: [...(secrets.custom_secret_values || []), ""],
    });
  };

  const updateEntry = (i, val) =>
    onChangeConfig({
      ...config,
      custom_entries: (config.custom_entries || []).map((e, idx) => idx === i ? val : e),
    });

  const updateEntrySecret = (i, val) => {
    const vals = [...(secrets.custom_secret_values || [])];
    while (vals.length <= i) vals.push("");
    vals[i] = val;
    onChangeSecrets({ ...secrets, custom_secret_values: vals });
  };

  const removeEntry = (i) => {
    onChangeConfig({
      ...config,
      custom_entries: (config.custom_entries || []).filter((_, idx) => idx !== i),
    });
    onChangeSecrets({
      ...secrets,
      custom_secret_values: (secrets.custom_secret_values || []).filter((_, idx) => idx !== i),
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* Auth type radio selector */}
      <div className="form-group">
        <label className="form-label">Auth type</label>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {AUTH_TYPES.map(t => {
            const selected   = auth_type === t.value;
            const { bg, color } = AUTH_COLORS[t.value];
            return (
              <label key={t.value} style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "10px 14px", borderRadius: "var(--radius-sm)",
                border: `1px solid ${selected ? color : "var(--border)"}`,
                background: selected ? bg : "var(--bg-card)",
                cursor: "pointer", transition: "all var(--transition)",
              }}>
                <input type="radio" name="auth_type" value={t.value}
                  checked={selected}
                  onChange={() => onChangeConfig({ ...DEFAULT_AUTH_CONFIG, auth_type: t.value })}
                  style={{ accentColor: color, flexShrink: 0 }} />
                <div>
                  <div style={{
                    fontSize: 13, fontWeight: selected ? 600 : 400,
                    color: selected ? color : "var(--text-primary)",
                  }}>
                    {t.label}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{t.desc}</div>
                </div>
              </label>
            );
          })}
        </div>
      </div>

      {/* ── API Key ─────────────────────────────────────────────────────────── */}
      {auth_type === "api_key" && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 12, padding: 14,
          borderRadius: "var(--radius-sm)", background: "#e0e7ff22", border: "1px solid #c7d2fe",
        }}>
          <div className="grid-2">
            <Field label="Inject location" tip={TIPS.api_key_location}>
              <select className="form-control" value={config.api_key_location || "header"}
                onChange={e => setC("api_key_location", e.target.value)}>
                <option value="header">Header</option>
                <option value="query_param">Query param</option>
              </select>
            </Field>
            <Field label="Key name" tip={TIPS.api_key_name} required>
              <input className="form-control" value={config.api_key_name || ""}
                placeholder="e.g. x-api-key, x-functions-key"
                onChange={e => setC("api_key_name", e.target.value)} />
            </Field>
          </div>
          <Field label="API key value" tip={TIPS.api_key_value} required>
            <PasswordInput
              value={secrets.api_key_value || ""}
              onChange={v => setS("api_key_value", v)}
              placeholder="Paste your API key here"
              hasExistingSecret={Boolean(config.api_key_secret_name)}
            />
            <SecretHint secretName={config.api_key_secret_name} />
          </Field>
        </div>
      )}

      {/* ── Bearer Token ────────────────────────────────────────────────────── */}
      {auth_type === "bearer_token" && (
        <div style={{
          padding: 14, borderRadius: "var(--radius-sm)",
          background: "#dcfce722", border: "1px solid #bbf7d0",
          display: "flex", flexDirection: "column", gap: 12,
        }}>
          <Field label="Bearer token value" tip={TIPS.bearer_token_value} required>
            <PasswordInput
              value={secrets.bearer_token_value || ""}
              onChange={v => setS("bearer_token_value", v)}
              placeholder="Paste your bearer token here"
              hasExistingSecret={Boolean(config.bearer_token_secret_name)}
            />
            <SecretHint secretName={config.bearer_token_secret_name} />
          </Field>
          <p className="form-hint">
            Produces: <code>Authorization: Bearer &lt;token&gt;</code>
          </p>
        </div>
      )}

      {/* ── Basic Auth ──────────────────────────────────────────────────────── */}
      {auth_type === "basic_auth" && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 12, padding: 14,
          borderRadius: "var(--radius-sm)", background: "#fef3c722", border: "1px solid #fde68a",
        }}>
          <div className="grid-2">
            <Field label="Username" tip={TIPS.basic_username} required>
              <input className="form-control" value={config.basic_auth_username || ""}
                placeholder="e.g. api_user"
                onChange={e => setC("basic_auth_username", e.target.value)} />
            </Field>
            <Field label="Password" tip={TIPS.basic_password} required>
              <PasswordInput
                value={secrets.basic_auth_password_value || ""}
                onChange={v => setS("basic_auth_password_value", v)}
                placeholder="Enter the password"
                hasExistingSecret={Boolean(config.basic_auth_password_secret_name)}
              />
              <SecretHint secretName={config.basic_auth_password_secret_name} />
            </Field>
          </div>
          <p className="form-hint">
            Produces: <code>Authorization: Basic &lt;base64(username:password)&gt;</code>
          </p>
        </div>
      )}

      {/* ── OAuth2 ──────────────────────────────────────────────────────────── */}
      {auth_type === "oauth2" && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 12, padding: 14,
          borderRadius: "var(--radius-sm)", background: "#ede9fe22", border: "1px solid #c4b5fd",
        }}>
          <Field label="Token endpoint URL" tip={TIPS.oauth2_token_url} required>
            <input className="form-control" value={config.oauth2_token_url || ""}
              placeholder="https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
              onChange={e => setC("oauth2_token_url", e.target.value)} />
          </Field>
          <div className="grid-2">
            <Field label="Client ID" tip={TIPS.oauth2_client_id} required>
              <input className="form-control" value={config.oauth2_client_id || ""}
                placeholder="e.g. a1b2c3d4-..."
                onChange={e => setC("oauth2_client_id", e.target.value)} />
            </Field>
            <Field label="Client secret" tip={TIPS.oauth2_client_secret} required>
              <PasswordInput
                value={secrets.oauth2_client_secret_value || ""}
                onChange={v => setS("oauth2_client_secret_value", v)}
                placeholder="Paste client secret here"
                hasExistingSecret={Boolean(config.oauth2_client_secret_name)}
              />
              <SecretHint secretName={config.oauth2_client_secret_name} />
            </Field>
          </div>
          <div className="grid-2">
            <Field label="Scopes (optional)" tip={TIPS.oauth2_scopes}>
              <input className="form-control" value={config.oauth2_scopes || ""}
                placeholder="https://service.azure.com/.default"
                onChange={e => setC("oauth2_scopes", e.target.value || null)} />
            </Field>
            <Field label="Token cache TTL (seconds)" tip={TIPS.oauth2_ttl}>
              <input className="form-control" type="number" min="60" max="86400"
                value={config.oauth2_token_ttl_seconds || 3600}
                onChange={e => setC("oauth2_token_ttl_seconds", parseInt(e.target.value) || 3600)} />
            </Field>
          </div>
          <div className="alert alert-info" style={{ padding: "8px 12px", fontSize: 12 }}>
            The orchestrator fetches a token using the client_credentials grant, caches it until expiry,
            and injects it as <code>Authorization: Bearer &lt;token&gt;</code>.
          </div>
        </div>
      )}

      {/* ── Custom ──────────────────────────────────────────────────────────── */}
      {auth_type === "custom" && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 10, padding: 14,
          borderRadius: "var(--radius-sm)", background: "#fce7f322", border: "1px solid #fbcfe8",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span className="form-label" style={{ marginBottom: 0 }}>
              Injection entries
              <span className="text-muted text-xs" style={{ marginLeft: 8, fontWeight: 400 }}>
                {(config.custom_entries || []).length} defined
              </span>
            </span>
            <button type="button" className="btn btn-secondary btn-sm" onClick={addEntry}>
              + Add entry
            </button>
          </div>
          {(config.custom_entries || []).length === 0
            ? <p className="form-hint">No entries. Add headers or query params to inject.</p>
            : (config.custom_entries || []).map((entry, i) => (
              <CustomEntryRow
                key={i}
                entry={entry}
                secret={(secrets.custom_secret_values || [])[i] || ""}
                onChangeEntry={val => updateEntry(i, val)}
                onChangeSecret={val => updateEntrySecret(i, val)}
                onRemove={() => removeEntry(i)}
              />
            ))
          }
        </div>
      )}
    </div>
  );
}
