"use client";

import { useState } from "react";
import Link from "next/link";
import { apiPost } from "@/lib/api-client";

export function LoginForm() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      // The server always returns the same generic response regardless of whether
      // the email matches an authorized account — see docs/access-model.md
      // "No Self-Registration" / spec section 9. Never treat this as confirmation
      // that an account exists.
      await apiPost("/auth/magic-link/request", { email });
      setSubmitted(true);
    } catch {
      setError("Something went wrong sending your sign-in link. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  if (submitted) {
    return (
      <div className="rounded border border-elavo-blue/40 bg-elavo-blue/10 p-5 text-sm text-white/85">
        If an authorized AlphaGasIQ account exists for this email, a secure sign-in link has
        been sent. Check your inbox for a message from AlphaGasIQ — the link expires in 15
        minutes.
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div>
        <label htmlFor="email" className="mb-1.5 block text-xs uppercase tracking-wide text-white/50">
          Business Email
        </label>
        <input
          id="email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@company.com"
          className="w-full rounded border border-white/15 bg-white/[0.03] px-3 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-elavo-blue focus:outline-none"
        />
      </div>
      {error && <p className="text-xs text-terminal-bear">{error}</p>}
      <button
        type="submit"
        disabled={loading || !email}
        className="w-full rounded bg-elavo-blue py-2.5 text-sm font-medium text-white hover:bg-elavo-blueLight disabled:cursor-not-allowed disabled:opacity-50"
      >
        {loading ? "Sending…" : "Send Secure Magic Link"}
      </button>
      <div className="flex items-center justify-between text-xs">
        <Link href="/trouble-signing-in" className="text-white/50 hover:text-elavo-blueLight">
          Trouble Signing In?
        </Link>
        <Link href="/" className="text-white/50 hover:text-elavo-blueLight">
          Back to AlphaGasIQ
        </Link>
      </div>
    </form>
  );
}
