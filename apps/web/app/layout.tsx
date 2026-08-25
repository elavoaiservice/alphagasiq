import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";

export const metadata: Metadata = {
  title: "AlphaGasIQ — Powered by Elavo AI",
  description: "Institutional-grade agentic natural gas intelligence & paper-trading platform.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-mono">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
