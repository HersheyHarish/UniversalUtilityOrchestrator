import React from "react";

export function ProactiveToast({ toast, onDismiss }) {
  if (!toast) return null;

  return (
    <div className="proactive-toast-container">
      <div className="proactive-toast" role="alert">
        <div className="proactive-toast-icon">🔔</div>
        <div className="proactive-toast-body">
          <div className="proactive-toast-title">{toast.title}</div>
          <p className="proactive-toast-message">{toast.body}</p>
          {toast.agents && (
            <p className="bill-explanation-meta" style={{ marginTop: 6, marginBottom: 0 }}>
              {toast.agents}
            </p>
          )}
        </div>
        <button
          type="button"
          className="proactive-toast-close"
          onClick={onDismiss}
          aria-label="Dismiss notification"
        >
          ×
        </button>
      </div>
    </div>
  );
}
