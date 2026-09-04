"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { API_BASE, apiGet } from "@/lib/api-client";

const DEV_USERS = [
  { label: "Trader", email: "trader@alphagasiq.local", password: "trader-dev-password" },
  { label: "Risk Manager", email: "risk@alphagasiq.local", password: "risk-dev-password" },
  { label: "Admin", email: "admin@alphagasiq.local", password: "admin-dev-password" },
];

export function AuthWidget() {
  const { user, login, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [oidcConfigured, setOidcConfigured] = useState(false);

  useEffect(() => {
    apiGet<{ oidc_configured: boolean }>("/auth/mode")
      .then((mode) => setOidcConfigured(mode.oidc_configured))
      .catch(() => setOidcConfigured(false));
  }, []);

  if (user) {
    return (
      <div className="flex items-center gap-2 text-[10px] text-terminal-muted">
        <span>
          {user.display_name} · {user.roles.join(", ")}
        </span>
        <button onClick={logout} className="border border-terminal-border rounded px-1.5 py-0.5 hover:text-terminal-text">
          Sign out
        </button>
      </div>
    );
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="text-[10px] border border-terminal-border rounded px-1.5 py-0.5 text-terminal-muted hover:text-terminal-text"
      >
        Sign in (dev)
      </button>
      {open && (
        <div className="absolute right-0 mt-1 z-10 bg-terminal-panel border border-terminal-border rounded p-2 w-56 text-xs">
          {oidcConfigured && (
            <>
              <button
                onClick={() => {
                  window.location.href = `${API_BASE}/auth/oidc/login`;
                }}
                className="block w-full text-left px-1.5 py-1 rounded border border-terminal-border mb-2 hover:bg-terminal-bg hover:text-terminal-accent"
              >
                Sign in with SSO
              </button>
              <div className="text-terminal-muted mb-1 border-t border-terminal-border pt-1">Or a dev-mode identity:</div>
            </>
          )}
          <div className="text-terminal-muted mb-1">
            Dev-mode identities — approving/rejecting trades and closing positions requires signing in.
          </div>
          {DEV_USERS.map((u) => (
            <button
              key={u.email}
              onClick={async () => {
                setError(null);
                try {
                  await login(u.email, u.password);
                  setOpen(false);
                } catch {
                  setError("Login failed");
                }
              }}
              className="block w-full text-left px-1.5 py-1 rounded hover:bg-terminal-bg hover:text-terminal-accent"
            >
              {u.label} <span className="text-terminal-muted">({u.email})</span>
            </button>
          ))}
          {error && <div className="text-terminal-bear mt-1">{error}</div>}
        </div>
      )}
    </div>
  );
}
