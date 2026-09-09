import Link from "next/link";
import { LoginForm } from "../login/LoginForm";
import { PoweredByElavo } from "@/components/common/PoweredByElavo";

export const metadata = { title: "Trouble Signing In — AlphaGasIQ" };

/**
 * Account recovery entry point (spec section 21). AlphaGasIQ is passwordless, so
 * "recovery" here means: request another Magic Link (same generic-response contract
 * as /login), or reach support. There is deliberately no self-service email-change
 * flow — changing an account's email requires administrator verification (section
 * 21), so that action isn't offered here at all, only via support contact.
 */
export default function TroubleSigningInPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-elavo-navy px-6 text-white">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <Link href="/" className="text-sm font-semibold tracking-tight">
            AlphaGasIQ
          </Link>
          <div className="mt-2 flex justify-center"><PoweredByElavo tone="dark" /></div>
        </div>
        <div className="rounded border border-white/10 bg-white/[0.02] p-6">
          <h1 className="text-lg font-semibold">Trouble Signing In?</h1>
          <p className="mt-1 mb-6 text-xs leading-relaxed text-white/50">
            Request another secure sign-in link below. If you no longer have access to the
            business email on your AlphaGasIQ account, an administrator must verify your
            identity before it can be changed — contact support rather than requesting a link.
          </p>
          <LoginForm />
          <div className="mt-6 border-t border-white/10 pt-4 text-xs text-white/50">
            Still can&rsquo;t get in, or lost access to your business email?{" "}
            <Link href="/contact" className="text-elavo-blueLight hover:underline">
              Contact support
            </Link>
            .
          </div>
        </div>
      </div>
    </div>
  );
}
