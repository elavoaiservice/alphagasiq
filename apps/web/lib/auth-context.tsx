"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { apiGet, apiPost } from "./api-client";

interface AuthUser {
  user_id: string;
  email: string;
  display_name: string;
  roles: string[];
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

const STORAGE_KEY = "alphagasiq.auth";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    // `/auth/oidc/callback` redirects back here with the session token in the URL
    // fragment (never the query string, so it never reaches server logs or a
    // Referer header). Picking it up client-side is what completes real SSO login.
    const hash = window.location.hash;
    if (hash.startsWith("#access_token=")) {
      const oidcToken = decodeURIComponent(hash.slice("#access_token=".length));
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      apiGet<AuthUser>("/auth/me", oidcToken)
        .then((oidcUser) => {
          setToken(oidcToken);
          setUser(oidcUser);
          try {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: oidcToken, user: oidcUser }));
          } catch {
            // ignore — private window / storage blocked
          }
        })
        .catch(() => {
          // Malformed/expired token from a stale redirect — fall through to whatever
          // (if anything) is already in localStorage below.
        });
      return;
    }

    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        setToken(parsed.token);
        setUser(parsed.user);
      }
    } catch {
      // ignore — private window / storage blocked
    }
  }, []);

  async function login(email: string, password: string) {
    const res = await apiPost<{ access_token: string; user: AuthUser }>("/auth/login", { email, password });
    setToken(res.access_token);
    setUser(res.user);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: res.access_token, user: res.user }));
    } catch {
      // ignore
    }
  }

  function logout() {
    setToken(null);
    setUser(null);
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }

  return <AuthContext.Provider value={{ token, user, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
