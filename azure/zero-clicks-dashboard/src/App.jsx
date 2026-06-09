import React from "react";
import { Routes, Route } from "react-router-dom";
import { useDashboard } from "./state/useDashboard";
import { Topbar } from "./components/Topbar";
import { ProactiveToast } from "./components/ProactiveToast";
import { DashboardHome } from "./pages/DashboardHome";
import { BillsAndPayments } from "./pages/BillsAndPayments";
import { Usage } from "./pages/Usage";
import { ServiceRequests } from "./pages/ServiceRequests";
import { Programs } from "./pages/Programs";
import { ReactiveEmail } from "./pages/ReactiveEmail";

export default function App() {
  const dashboardProps = useDashboard();

  return (
    <div className="layout">
      <Topbar
        customerId={dashboardProps.customerId}
        orchStatus={dashboardProps.orchStatus}
        onProactiveTrigger={dashboardProps.triggerProactiveNotification}
        proactiveLoading={dashboardProps.proactiveLoading}
        hasUnreadProactive={dashboardProps.hasUnreadProactive}
        activeAgents={dashboardProps.activeAgents}
      />

      <ProactiveToast
        toast={dashboardProps.proactiveToast}
        onDismiss={dashboardProps.dismissToast}
      />

      <Routes>
        <Route path="/" element={<DashboardHome {...dashboardProps} />} />
        <Route path="/bills" element={<BillsAndPayments />} />
        <Route path="/usage" element={<Usage usageData={dashboardProps.usageData} />} />
        <Route path="/service-requests" element={<ServiceRequests />} />
        <Route path="/programs" element={<Programs />} />
        <Route path="/reactive-email" element={<ReactiveEmail {...dashboardProps} />} />
      </Routes>
    </div>
  );
}
