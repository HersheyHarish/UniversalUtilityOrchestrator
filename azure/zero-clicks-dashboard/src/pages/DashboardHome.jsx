import React from "react";
import { BillingHero } from "../components/BillingHero";
import { BillExplanation } from "../components/BillExplanation";
import { UsageChart } from "../components/UsageChart";
import { BillBreakdown } from "../components/BillBreakdown";
import { AgentFeed } from "../components/AgentFeed";
import { CopilotChat } from "../components/CopilotChat";
import { AlertsPanel } from "../components/AlertsPanel";
import { ServiceQuickLinks } from "../components/ServiceQuickLinks";

export function DashboardHome({
  billing,
  usageData,
  agentEvents,
  realAlerts,
  billExplanation,
  billExplanationLoading,
  billExplanationError,
  billExplanationAgents,
  refetchBillExplanation,
  chatMessages,
  chatInput,
  setChatInput,
  chatLoading,
  sendChat,
  ackAlert,
}) {
  return (
    <div className="main-content">
      {/* ── LEFT COLUMN ── */}
      <div className="main-left">
        <BillingHero billing={billing} />
        <BillExplanation
          explanation={billExplanation}
          loading={billExplanationLoading}
          error={billExplanationError}
          agents={billExplanationAgents}
          onRetry={refetchBillExplanation}
        />
        <UsageChart usageData={usageData} />
        <BillBreakdown billing={billing} />
        <AgentFeed agentEvents={agentEvents} />
        <CopilotChat
          chatMessages={chatMessages}
          chatInput={chatInput}
          setChatInput={setChatInput}
          chatLoading={chatLoading}
          sendChat={sendChat}
        />
      </div>

      {/* ── RIGHT COLUMN ── */}
      <div className="main-right">
        <ServiceQuickLinks />
        <AlertsPanel realAlerts={realAlerts} onAckAlert={ackAlert} />
      </div>
    </div>
  );
}
