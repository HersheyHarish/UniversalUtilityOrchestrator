import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext.jsx";
import Layout from "./components/Layout.jsx";
import LoginPage from "./components/LoginPage.jsx";
import Dashboard from "./components/Dashboard.jsx";
import AgentList from "./components/AgentList.jsx";
import AgentDetail from "./components/AgentDetail.jsx";
import HealthMonitor from "./components/HealthMonitor.jsx";
import TraceExplorer from "./components/TraceExplorer.jsx";
import TraceDetail from "./components/TraceDetail.jsx";
import MetricsDashboard from "./components/MetricsDashboard.jsx";


function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="loading-screen">
        <div className="spinner spinner-lg" />
        <span>Verifying session…</span>
      </div>
    );
  }
  return user ? children : <Navigate to="/login" replace />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="agents" element={<AgentList />} />
        <Route path="agents/:id" element={<AgentDetail />} />
        <Route path="health" element={<HealthMonitor />} />
        <Route path="traces" element={<TraceExplorer />} />
        <Route path="traces/:id" element={<TraceDetail />} />
        <Route path="metrics" element={<MetricsDashboard />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}
