import React, { useState } from "react";

export function Tooltip({ text, children }) {
  const [show, setShow] = useState(false);
  return (
    <span className="tooltip-wrap"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}>
      {children}
      {show && <span className="tooltip-box">{text}</span>}
    </span>
  );
}

export function TooltipIcon({ text }) {
  return <Tooltip text={text}><span className="tooltip-icon">?</span></Tooltip>;
}

export function StatusBadge({ status }) {
  const cls = { active: "badge badge-active", inactive: "badge badge-inactive",
                degraded: "badge badge-degraded" }[status] || "badge badge-inactive";
  const dot = { active: "#22c55e", inactive: "#94a3b8", degraded: "#f59e0b" }[status] || "#94a3b8";
  return (
    <span className={cls}>
      <span className="badge-dot" style={{ background: dot }} />
      {status}
    </span>
  );
}

export function HealthDot({ status }) {
  const cls = { healthy: "health-dot health-healthy",
                unhealthy: "health-dot health-unhealthy",
                unreachable: "health-dot health-unreachable" }[status] || "health-dot health-unknown";
  return <span className={cls} title={status || "unknown"} />;
}

export function Spinner({ large }) {
  return <div className={large ? "spinner spinner-lg" : "spinner"} />;
}

export function EmptyState({ icon = "📋", title, desc, action }) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <div className="empty-title">{title}</div>
      {desc   && <div className="empty-desc">{desc}</div>}
      {action}
    </div>
  );
}

export function Alert({ type = "error", children, onClose }) {
  return (
    <div className={`alert alert-${type}`}
      style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
      <span style={{ flex: 1 }}>{children}</span>
      {onClose && (
        <button onClick={onClose} style={{ background: "none", border: "none",
          cursor: "pointer", fontSize: 18, lineHeight: 1, opacity: .6, padding: 0 }}>
          ×
        </button>
      )}
    </div>
  );
}

export function TagList({ tags = [] }) {
  if (!tags.length) return <span className="text-muted text-xs">—</span>;
  return (
    <div className="tag-list">
      {tags.map(t => <span key={t} className="badge badge-tag">{t}</span>)}
    </div>
  );
}

export function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); } catch (_) {}
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button className="btn btn-ghost btn-sm" onClick={copy} title="Copy"
      style={{ padding: "3px 6px", fontSize: 11, color: "var(--text-muted)" }}>
      {copied ? "✓ copied" : "⎘ copy"}
    </button>
  );
}

export function ConfirmModal({ title, message, confirmLabel = "Confirm",
  danger = false, onConfirm, onCancel }) {
  const [loading, setLoading] = useState(false);
  const go = async () => {
    setLoading(true);
    try { await onConfirm(); } finally { setLoading(false); }
  };
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" style={{ maxWidth: 420 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">{title}</span>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onCancel}>×</button>
        </div>
        <div className="modal-body">
          <p style={{ fontSize: 14, color: "var(--text-secondary)", lineHeight: 1.6 }}>{message}</p>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button className={`btn ${danger ? "btn-danger" : "btn-primary"}`}
            onClick={go} disabled={loading}>
            {loading ? <Spinner /> : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
