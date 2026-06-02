import React from "react";
import { FormattedExplanation } from "./FormattedExplanation";

export function BillExplanation({
  explanation,
  loading,
  error,
  agents,
  onRetry,
}) {
  return (
    <div className="bill-explanation">
      <div className="bill-explanation-header">
        <div className="bill-explanation-title">
          <span>🧾</span>
          Why your bill looks this way
        </div>
        {!loading && !error && (
          <span className="tag reactive">Billing Agent</span>
        )}
      </div>

      {loading && (
        <div className="bill-explanation-loading">
          <div className="chat-bubble assistant thinking" style={{ padding: "10px 14px" }}>
            <div className="thinking-dot" />
            <div className="thinking-dot" />
            <div className="thinking-dot" />
          </div>
          <div className="bill-explanation-skeleton-lines">
            <div className="skeleton" />
            <div className="skeleton" />
            <div className="skeleton" />
          </div>
        </div>
      )}

      {!loading && error && (
        <>
          <p className="bill-explanation-error">{error}</p>
          <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
            Retry
          </button>
        </>
      )}

      {!loading && !error && explanation && (
        <>
          <FormattedExplanation text={explanation} className="bill-explanation-content" />
          {agents?.length > 0 && (
            <p className="bill-explanation-meta">
              Powered by {agents.join(", ")} via Orchestrator
            </p>
          )}
        </>
      )}
    </div>
  );
}
