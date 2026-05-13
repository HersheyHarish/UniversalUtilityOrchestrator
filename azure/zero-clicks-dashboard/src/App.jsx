import React from "react";
import { useDashboardData } from "./state/useDashboardData";
import { InsightsSection } from "./components/InsightsSection";
import { CopilotSection } from "./components/CopilotSection";
import { AlertsSection } from "./components/AlertsSection";

export default function App() {
  const {
    customerId,
    sinceHours,
    insights,
    alerts,
    copilotContext,
    selectedDate,
    loading,
    error,
    onDateSelect,
    onAckAlert,
    onInsightAction,
  } = useDashboardData();

  return (
    <div className="page">
      <header className="hero">
        <h1>Universal Utility Zero-Clicks Dashboard</h1>
        <p>
          Customer <strong>{customerId}</strong> · Last {sinceHours}h
        </p>
      </header>

      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="loading-banner">Loading AI insights...</div>}

      <InsightsSection insights={insights} onInsightAction={onInsightAction} />
      <CopilotSection
        selectedDate={selectedDate}
        context={copilotContext}
        onDateSelect={onDateSelect}
      />
      <AlertsSection alerts={alerts} onAckAlert={onAckAlert} />
    </div>
  );
}
