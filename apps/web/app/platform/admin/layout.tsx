"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

const NAV = [
  { href: "/platform/admin", label: "Overview" },
  { href: "/platform/admin/users", label: "Users" },
  { href: "/platform/admin/organizations", label: "Organizations" },
  { href: "/platform/admin/features", label: "Features" },
  { href: "/platform/admin/settings", label: "System Settings" },
  { href: "/platform/admin/data-feeds", label: "Data Feeds" },
  { href: "/platform/admin/configuration", label: "Configuration" },
  { href: "/platform/admin/token-usage", label: "Token Usage" },
  { href: "/platform/admin/workspaces", label: "Workspaces" },
  { href: "/platform/admin/enterprise-data", label: "Enterprise Data" },
  { href: "/platform/admin/agents", label: "Agents" },
  { href: "/platform/admin/models", label: "Models" },
  { href: "/platform/admin/risk-settings", label: "Risk Settings" },
  { href: "/platform/admin/audit-log", label: "Audit Log" },
  { href: "/platform/admin/system-health", label: "System Health" },
  { href: "/platform/admin/upgrade", label: "Upgrade" },
  { href: "/platform/admin/changelog", label: "Changelog" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const pathname = usePathname();

  // UI-only gate -- the real enforcement is every /admin/* endpoint's
  // require_permission check (docs/access-model.md §5). Hiding the console for a
  // non-admin caller is just UX; a determined caller still gets 403 from the API.
  if (!user || !user.roles.includes("ADMIN")) {
    return (
      <div className="panel max-w-md">
        <div className="panel-title">AlphaGasIQ Administration</div>
        <p className="text-xs text-terminal-muted">
          Sign in to an account with administrator permissions to access this console.
        </p>
      </div>
    );
  }

  return (
    <div className="flex gap-4">
      <nav className="w-44 shrink-0 border-r border-terminal-border pr-3 text-xs flex flex-col gap-1.5">
        <div className="panel-title mb-1">Administration</div>
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={
              pathname === item.href
                ? "text-terminal-accent"
                : "text-terminal-muted hover:text-terminal-text"
            }
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  );
}
