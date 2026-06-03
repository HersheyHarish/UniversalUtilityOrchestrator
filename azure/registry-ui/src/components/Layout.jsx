import React, { useEffect } from "react";
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { IcDashboard, IcAgents, IcHealth, IcLogOut, IcMetrics, IcTrace } from "./Icons.jsx";
import { agents as agentsApi } from "../api/client.js";

const NAV = [
  { path: "/dashboard", label: "Dashboard", Icon: IcDashboard },
  { path: "/agents", label: "Agents", Icon: IcAgents },
  { path: "/metrics", label: "Monitoring", Icon: IcMetrics },
  { path: "/traces", label: "Tracing", Icon: IcTrace },
  { path: "/health", label: "Health monitor", Icon: IcHealth },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  // Background cold-start pinging loop
  useEffect(() => {
    let timerId = null;
    const checkAndPing = async () => {
      const enabled = localStorage.getItem("coldStartPingEnabled") === "true";
      if (!enabled) {
        timerId = setTimeout(checkAndPing, 2000);
        return;
      }

      const intervalMs = parseInt(localStorage.getItem("coldStartPingInterval") || "30000", 10);
      const lastPingTime = parseInt(localStorage.getItem("coldStartLastPingTime") || "0", 10);
      const now = Date.now();

      if (now - lastPingTime >= intervalMs) {
        localStorage.setItem("coldStartLastPingTime", String(now));
        // Emit trigger event
        window.dispatchEvent(new CustomEvent("coldStartPingTriggered", { detail: { timestamp: now } }));
        try {
          const res = await agentsApi.pingAll();
          localStorage.setItem("coldStartLastPingStatus", "success");
          localStorage.setItem("coldStartLastPingTimestamp", String(Date.now()));
          window.dispatchEvent(new CustomEvent("coldStartPingSuccess", { detail: { timestamp: Date.now(), results: res.results } }));
        } catch (e) {
          console.warn("Background cold-start ping failed:", e);
          localStorage.setItem("coldStartLastPingStatus", "error");
          localStorage.setItem("coldStartLastPingError", e.message || "Failed to contact registry");
          localStorage.setItem("coldStartLastPingTimestamp", String(Date.now()));
          window.dispatchEvent(new CustomEvent("coldStartPingFailed", { detail: { timestamp: Date.now(), error: e.message } }));
        }
      }

      timerId = setTimeout(checkAndPing, 2000);
    };

    timerId = setTimeout(checkAndPing, 2000);
    return () => clearTimeout(timerId);
  }, []);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const pageLabel = NAV.find(n => pathname.startsWith(n.path))?.label ?? "Registry";

  return (
    <div className="app-shell">
      {/* ── Sidebar ─────────────────────────────────────────────── */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="logo-icon">A</div>
          <div>
            <div className="logo-text">Agent Registry</div>
            <div className="logo-sub">Universal Utility Agent</div>
          </div>
        </div>

        <nav className="sidebar-nav">
          <div className="nav-section-label">Navigation</div>
          {NAV.map(({ path, label, Icon }) => (
            <button key={path}
              className={`nav-item ${pathname.startsWith(path) ? "active" : ""}`}
              onClick={() => navigate(path)}>
              <Icon size={15} />
              {label}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="user-chip">
            <div className="user-avatar">
              {(user?.username?.[0] || "A").toUpperCase()}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="user-name truncate">{user?.username || "admin"}</div>
              <div className="user-role">Administrator</div>
            </div>
            <button className="btn btn-ghost btn-icon btn-sm" onClick={handleLogout}
              title="Log out"
              style={{ color: "rgba(255,255,255,.4)", flexShrink: 0, padding: 6 }}>
              <IcLogOut size={14} />
            </button>
          </div>
        </div>
      </aside>

      {/* ── Main area ────────────────────────────────────────────── */}
      <div className="main-area">
        <header className="topbar">
          <span style={{ flex: 1, fontWeight: 600 }}>{pageLabel}</span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Registry Admin
          </span>
        </header>
        <div className="page-body">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
