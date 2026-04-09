import React, { createContext, useContext, useEffect, useState } from "react";
import { auth } from "../api/client.js";

const Ctx = createContext(null);

export function AuthProvider({ children }) {
  const [user,    setUser]    = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = sessionStorage.getItem("session_token");
    if (!t) { setLoading(false); return; }
    auth.verify()
      .then((r) => {
        if (r.valid) setUser({ token: t, username: r.username || sessionStorage.getItem("username") || "admin" });
        else         sessionStorage.clear();
      })
      .catch(() => sessionStorage.clear())
      .finally(() => setLoading(false));
  }, []);

  const login = async (username, password) => {
    const r = await auth.login(username, password);
    sessionStorage.setItem("session_token", r.token);
    sessionStorage.setItem("username",      r.username || username);
    setUser({ token: r.token, username: r.username || username });
    return r;
  };

  const logout = async () => {
    try { await auth.logout(); } catch (_) {}
    sessionStorage.clear();
    setUser(null);
  };

  return <Ctx.Provider value={{ user, loading, login, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
