"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { apiPost } from "./api-client";

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
