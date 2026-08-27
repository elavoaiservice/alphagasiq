"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/platform/alpha-intelligence", label: "Overview" },
  { href: "/platform/alpha-intelligence/signals", label: "AlphaSignal" },
  { href: "/platform/alpha-intelligence/impacts", label: "AlphaImpact" },
  { href: "/platform/alpha-intelligence/consensus", label: "AlphaConsensus" },
  { href: "/platform/alpha-intelligence/scenarios", label: "AlphaScenario" },
  { href: "/platform/alpha-intelligence/memory", label: "AlphaMemory" },
  { href: "/platform/alpha-intelligence/replay", label: "AlphaReplay" },
];

export default function AlphaIntelligenceLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex gap-4">
      <nav className="w-44 shrink-0 border-r border-terminal-border pr-3 text-xs flex flex-col gap-1.5">
        <div className="panel-title mb-1">Alpha Intelligence</div>
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
