import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { agents as agentsApi } from "../api/client.js";
import { Spinner, HealthDot, Alert } from "./Primitives.jsx";
import { IcZap, IcChevronRight } from "./Icons.jsx";

function HealthCard({ result, onClick }) {
  const isHealthy = result.status === "healthy";
  const borderColor = { healthy: "var(--c-success)", unhealthy: "var(--c-danger)",
                        unreachable: "var(--text-muted)" }[result.status] || "var(--border)";
  return (
    <div onClick={onClick} style={{ background: "var(--bg-card)",
      border: `1px solid ${borderColor}`, borderRadius: "var(--radius)",
      padding: 16, cursor: "pointer", boxShadow: "var(--shadow-sm)",
      transition: "box-shadow var(--transition), transform var(--transition)" }}
      onMouseEnter={e => { e.currentTarget.style.boxShadow = "var(--shadow-md)";
        e.currentTarget.style.transform = "translateY(-1px)"; }}
      onMouseLeave={e => { e.currentTarget.style.boxShadow = "var(--shadow-sm)";
        e.currentTarget.style.transform = ""; }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <HealthDot status={result.status} />
        <span style={{ fontWeight: 600, fontSize: 14, flex: 1 }}>{result.agent_name}</span>
        <IcChevronRight size={13} style={{ color: "var(--text-muted)" }} />
      </div>
      <div style={{ fontSize: 26, fontWeight: 700, marginBottom: 4,
        color: isHealthy ? "var(--c-success-text)" : "var(--c-danger-text)" }}>
        {result.response_ms != null ? `${result.response_ms} ms` : "—"}
      </div>
      <div className="text-xs text-muted" style={{ textTransform: "capitalize" }}>
        {result.status}
        {result.http_code && ` · HTTP ${result.http_code}`}
      </div>
      {result.error && (
        <div style={{ fontSize: 11, color: "var(--c-danger-text)",
          marginTop: 6, wordBreak: "break-all" }}>{result.error}</div>
      )}
      <div className="text-xs text-muted" style={{ marginTop: 8 }}>
        {result.checked_at?.slice(0, 19).replace("T", " ")} UTC
      </div>
    </div>
  );
}

export default function HealthMonitor() {
  const navigate          = useNavigate();
  const [results,  setResults]  = useState([]);
  const [summary,  setSummary]  = useState(null);
  const [loading,  setLoading]  = useState(false);
  const [autoRun,  setAutoRun]  = useState(false);
  const [error,    setError]    = useState("");
  const [lastRun,  setLastRun]  = useState(null);

  // Cold Start Pinger configuration state
  const [coldStartEnabled, setColdStartEnabled] = useState(
    localStorage.getItem("coldStartPingEnabled") === "true"
  );
  const [coldStartInterval, setColdStartInterval] = useState(
    parseInt(localStorage.getItem("coldStartPingInterval") || "30000", 10)
  );
  const [coldStartCountdown, setColdStartCountdown] = useState(null);
  const [coldStartStatusLog, setColdStartStatusLog] = useState("");

  const run = async () => {
    setLoading(true); setError("");
    try {
      const res = await agentsApi.pingAll();
      setResults(res.results || []);
      setSummary({ checked: res.checked, healthy: res.healthy, degraded: res.degraded });
      setLastRun(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Regular auto-refresh timer (foreground check)
  useEffect(() => {
    if (!autoRun) return;
    const id = setInterval(run, 60_000);
    return () => clearInterval(id);
  }, [autoRun]);

  // Cold Start live timer
  useEffect(() => {
    if (!coldStartEnabled) {
      setColdStartCountdown(null);
      return;
    }

    const updateTimer = () => {
      const lastPing = parseInt(localStorage.getItem("coldStartLastPingTime") || "0", 10);
      const now = Date.now();
      const diff = now - lastPing;
      const rem = Math.max(0, Math.ceil((coldStartInterval - diff) / 1000));
      setColdStartCountdown(rem);

      // Build live status message
      const status = localStorage.getItem("coldStartLastPingStatus") || "";
      const timestampStr = localStorage.getItem("coldStartLastPingTimestamp");
      if (timestampStr) {
        const time = new Date(parseInt(timestampStr, 10)).toLocaleTimeString();
        if (status === "success") {
          setColdStartStatusLog(`Last background check: SUCCESS at ${time}`);
        } else if (status === "error") {
          const err = localStorage.getItem("coldStartLastPingError") || "Unknown error";
          setColdStartStatusLog(`Last background check: FAILED at ${time} (${err})`);
        }
      }
    };

    updateTimer();
    const timerId = setInterval(updateTimer, 1000);
    return () => clearInterval(timerId);
  }, [coldStartEnabled, coldStartInterval]);

  // Listen to custom window events triggered by Layout background loop
  useEffect(() => {
    const handlePingTriggered = () => {
      setLoading(true);
      setError("");
    };

    const handlePingSuccess = (e) => {
      setLoading(false);
      if (e.detail?.results) {
        setResults(e.detail.results);
        const checked = e.detail.results.length;
        const healthy = e.detail.results.filter(r => r.status === "healthy").length;
        const degraded = e.detail.results.filter(r => r.status === "degraded").length;
        setSummary({ checked, healthy, degraded });
      }
      setLastRun(new Date().toLocaleTimeString());
    };

    const handlePingFailed = (e) => {
      setLoading(false);
      setError(e.detail?.error || "Background check failed.");
    };

    window.addEventListener("coldStartPingTriggered", handlePingTriggered);
    window.addEventListener("coldStartPingSuccess", handlePingSuccess);
    window.addEventListener("coldStartPingFailed", handlePingFailed);

    return () => {
      window.removeEventListener("coldStartPingTriggered", handlePingTriggered);
      window.removeEventListener("coldStartPingSuccess", handlePingSuccess);
      window.removeEventListener("coldStartPingFailed", handlePingFailed);
    };
  }, []);

  const handleToggleColdStart = (e) => {
    const val = e.target.checked;
    setColdStartEnabled(val);
    localStorage.setItem("coldStartPingEnabled", String(val));
    if (val) {
      localStorage.setItem("coldStartLastPingTime", String(Date.now()));
    }
  };

  const handleChangeInterval = (e) => {
    const val = parseInt(e.target.value, 10);
    setColdStartInterval(val);
    localStorage.setItem("coldStartPingInterval", String(val));
    localStorage.setItem("coldStartLastPingTime", String(Date.now()));
  };

  const healthy   = results.filter(r => r.status === "healthy");
  const unhealthy = results.filter(r => r.status !== "healthy");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      
      {/* Page Header */}
      <div className="page-header">
        <div>
          <div className="page-title">Health monitor</div>
          <div className="page-desc">
            Probe all active agents and update their status in the registry.
            {lastRun && (
              <span style={{ color: "var(--c-primary)", marginLeft: 8 }}>
                Last run: {lastRun}
              </span>
            )}
          </div>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 7,
            fontSize: 13, color: "var(--text-secondary)", cursor: "pointer" }}>
            <input type="checkbox" checked={autoRun}
              onChange={e => setAutoRun(e.target.checked)}
              style={{ width: 14, height: 14, cursor: "pointer" }} />
            Auto-refresh (60 s)
          </label>
          <button className="btn btn-primary" onClick={run} disabled={loading}>
            {loading
              ? <><Spinner /> Running…</>
              : <><IcZap size={14} /> Run health check</>}
          </button>
        </div>
      </div>

      {error && <Alert type="error" onClose={() => setError("")}>{error}</Alert>}

      {/* ── Cold Start Pinging Panel ── */}
      <div className="card" style={{ padding: "16px 20px" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 24, alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
            <div style={{ fontSize: 24 }}>❄️</div>
            <div>
              <div style={{ fontWeight: 600, fontSize: 15, display: "flex", alignItems: "center", gap: 8 }}>
                Cold Start Prevention Pinger
                {coldStartEnabled && (
                  <span className="badge badge-success" style={{ padding: "2px 8px", fontSize: 10 }}>Active</span>
                )}
              </div>
              <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 4 }}>
                Keep agent containers warm by continuously pinging them in the background.
              </div>
            </div>
          </div>
          
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 500, cursor: "pointer" }}>
              <input type="checkbox" checked={coldStartEnabled} onChange={handleToggleColdStart}
                style={{ width: 16, height: 16, cursor: "pointer" }} />
              Enable background pinging
            </label>

            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>Interval:</span>
              <select className="form-control" value={coldStartInterval} onChange={handleChangeInterval}
                disabled={!coldStartEnabled} style={{ padding: "4px 8px", fontSize: 13, width: 120 }}>
                <option value="10000">10 seconds</option>
                <option value="30000">30 seconds</option>
                <option value="60000">1 minute</option>
                <option value="300000">5 minutes</option>
                <option value="600000">10 minutes</option>
              </select>
            </div>
          </div>
        </div>

        {coldStartEnabled && (
          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 12,
            borderTop: "1px solid var(--border)", marginTop: 12, paddingTop: 12, fontSize: 13 }}>
            <span style={{ color: "var(--text-secondary)" }}>
              {coldStartStatusLog || "Waiting for first background ping..."}
            </span>
            {coldStartCountdown !== null && (
              <span style={{ fontWeight: 600, color: "var(--c-primary)" }}>
                Next ping in: {coldStartCountdown}s
              </span>
            )}
          </div>
        )}
      </div>

      {/* Summary pills */}
      {summary && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {[
            { label: "Checked",  value: summary.checked,  bg: "var(--c-primary-light)",  color: "var(--c-primary-text)" },
            { label: "Healthy",  value: summary.healthy,  bg: "var(--c-success-bg)",     color: "var(--c-success-text)" },
            { label: "Degraded", value: summary.degraded, bg: "var(--c-warning-bg)",     color: "var(--c-warning-text)" },
          ].map(({ label, value, bg, color }) => (
            <div key={label} style={{ padding: "12px 20px", borderRadius: "var(--radius)",
              background: bg, minWidth: 100, textAlign: "center" }}>
              <div style={{ fontSize: 26, fontWeight: 700, color }}>{value}</div>
              <div style={{ fontSize: 12, color, opacity: .85 }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Idle state */}
      {results.length === 0 && !loading && (
        <div className="card">
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center",
            padding: "64px 24px", gap: 16, textAlign: "center" }}>
            <div style={{ fontSize: 40 }}>💓</div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>No health data yet</div>
            <div className="text-sm text-muted" style={{ maxWidth: 340, lineHeight: 1.6 }}>
              Click "Run health check" to probe all active agents. The registry will
              automatically update each agent's status based on the probe result.
            </div>
            <button className="btn btn-primary" onClick={run}>
              <IcZap size={14} /> Run health check
            </button>
          </div>
        </div>
      )}

      {/* Needs attention */}
      {unhealthy.length > 0 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--c-danger-text)",
            marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%",
              background: "var(--c-danger)", display: "inline-block" }} />
            Needs attention ({unhealthy.length})
          </div>
          <div className="grid-3">
            {unhealthy.map(r => (
              <HealthCard key={r.agent_id} result={r}
                onClick={() => navigate(`/agents/${r.agent_id}`)} />
            ))}
          </div>
        </div>
      )}

      {/* Healthy */}
      {healthy.length > 0 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--c-success-text)",
            marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%",
              background: "var(--c-success)", display: "inline-block" }} />
            Healthy ({healthy.length})
          </div>
          <div className="grid-3">
            {healthy.map(r => (
              <HealthCard key={r.agent_id} result={r}
                onClick={() => navigate(`/agents/${r.agent_id}`)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
