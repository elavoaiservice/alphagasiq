import Link from "next/link";
import { LoginForm } from "./LoginForm";
import { PoweredByElavo } from "@/components/common/PoweredByElavo";

export const metadata = { title: "Sign In — AlphaGasIQ" };

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-elavo-navy px-6 text-white">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <Link href="/" className="text-sm font-semibold tracking-tight">
            AlphaGasIQ
          </Link>
          <div className="mt-2 flex justify-center"><PoweredByElavo tone="dark" /></div>
        </div>
        <div className="rounded border border-white/10 bg-white/[0.02] p-6">
          <h1 className="text-lg font-semibold">Sign In to AlphaGasIQ</h1>
          <p className="mt-1 mb-6 text-xs leading-relaxed text-white/50">
            AlphaGasIQ is a restricted-access platform. Only authorized users may sign in.
          </p>
          <LoginForm />
        </div>
      </div>
    </div>
  );
}
