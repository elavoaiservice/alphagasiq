import { HeaderBar } from "@/components/header/HeaderBar";
import Link from "next/link";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-terminal-bg text-terminal-text">
      <HeaderBar />
      <div className="flex">
        <nav className="w-40 border-r border-terminal-border bg-terminal-panel p-3 text-xs flex flex-col gap-2">
          <Link href="/" className="hover:text-terminal-accent">
            Dashboard
          </Link>
          <Link href="/chat" className="hover:text-terminal-accent">
            AI Trader Chat
          </Link>
          <Link href="/pipeline-map" className="hover:text-terminal-accent">
            Pipeline Map
          </Link>
          <Link href="/model-performance" className="hover:text-terminal-accent">
            Model Performance
          </Link>
        </nav>
        <main className="flex-1 p-4">{children}</main>
      </div>
    </div>
  );
}
