import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";

export const metadata: Metadata = {
  title: "AlphaGasIQ — Powered by Elavo AI",
  description: "Institutional-grade agentic natural gas intelligence & paper-trading platform.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // Font: match ElavoAI exactly. ElavoAI names Inter first in a system-font
  // fallback stack but does NOT bundle/load Inter (no next/font, Google Fonts,
  // or @font-face) — so it renders in the OS UI font. We mirror that stack (in
  // tailwind `font-sans`) and intentionally do not force-load Inter, so both
  // apps render identically on the same machine.
  return (
    <html lang="en">
      <body className="font-sans">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
