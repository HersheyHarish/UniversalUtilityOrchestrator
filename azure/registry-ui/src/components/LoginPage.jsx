import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { Alert, Spinner } from "./Primitives.jsx";

export default function LoginPage() {
  const { login, user } = useAuth();
  const navigate        = useNavigate();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(false);

  useEffect(() => {
    if (user) navigate("/dashboard", { replace: true });
  }, [user, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError("Username and password are required.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      await login(username.trim(), password);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err.message || "Invalid credentials. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 32 }}>
          <div className="logo-icon" style={{ width: 48, height: 48, fontSize: 22,
            flexShrink: 0, background: "var(--c-primary)", borderRadius: "var(--radius)",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "#fff", fontWeight: 700 }}>
            A
          </div>
          <div>
            <div style={{ fontSize: 22, fontWeight: 700 }}>Agent Registry</div>
            <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 2 }}>
              Sign in to manage your agent ecosystem
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {error && <Alert type="error" onClose={() => setError("")}>{error}</Alert>}

          <div className="form-group">
            <label className="form-label">
              Username <span className="form-required">*</span>
            </label>
            <input className="form-control" type="text" placeholder="admin"
              value={username} onChange={e => setUsername(e.target.value)}
              autoFocus autoComplete="username" />
          </div>

          <div className="form-group">
            <label className="form-label">
              Password <span className="form-required">*</span>
            </label>
            <input className="form-control" type="password" placeholder="••••••••"
              value={password} onChange={e => setPassword(e.target.value)}
              autoComplete="current-password" />
            <span className="form-hint">
              Credentials are stored securely in Azure Key Vault.
            </span>
          </div>

          <button className="btn btn-primary btn-lg w-full" type="submit" disabled={loading}>
            {loading ? <><Spinner /> Signing in…</> : "Sign in"}
          </button>
        </form>

        <p style={{ marginTop: 24, fontSize: 12, color: "var(--text-muted)",
          textAlign: "center", lineHeight: 1.6 }}>
          Session expires after 8 hours · Credentials managed via Azure Key Vault
        </p>
      </div>
    </div>
  );
}
