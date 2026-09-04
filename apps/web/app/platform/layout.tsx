import { HeaderBar } from "@/components/header/HeaderBar";
import { LiveEventsProvider } from "@/lib/live-events-context";
import Link from "next/link";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <LiveEventsProvider>
      <div className="min-h-screen bg-terminal-bg text-terminal-text">
        <HeaderBar />
        <div className="flex">
          <nav className="w-40 border-r border-terminal-border bg-terminal-panel p-3 text-xs flex flex-col gap-2">
            <Link href="/platform" className="hover:text-terminal-accent">
              Dashboard
            </Link>
            <Link href="/platform/chat" className="hover:text-terminal-accent">
              AI Trader Chat
            </Link>
            <Link href="/platform/pipeline-map" className="hover:text-terminal-accent">
              Pipeline Map
            </Link>
            <Link href="/platform/model-performance" className="hover:text-terminal-accent">
              Model Performance
            </Link>
            <Link href="/platform/alpha-intelligence" className="hover:text-terminal-accent">
              Alpha Intelligence
            </Link>
            <div className="mt-2 border-t border-terminal-border pt-2">
              <Link href="/platform/admin" className="hover:text-terminal-accent">
                Admin
              </Link>
            </div>
          </nav>
          <main className="flex-1 p-4">{children}</main>
        </div>
      </div>
    </LiveEventsProvider>
  );
}
