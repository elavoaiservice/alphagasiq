import Link from "next/link";
import { LoginForm } from "./LoginForm";
import { PoweredByElavo } from "@/components/common/PoweredByElavo";

export const metadata = { title: "Sign In — AlphaGasIQ" };

export default function LoginPage() {
  return (
    <div className="min-h-screen bg-white">
      <div className="mx-auto flex max-w-md flex-col items-center px-6 py-16">
        <div className="text-center">
          <Link href="/" className="text-2xl font-semibold tracking-tight text-terminal-text">
            AlphaGasIQ
          </Link>
          <div className="mt-3 flex justify-center"><PoweredByElavo /></div>
        </div>
        <div className="mt-10 w-full rounded-[28px] border border-[#c8e6f7] bg-white p-8 shadow-lg">
          <div className="mb-6 text-center">
            <h1 className="text-2xl font-semibold tracking-tight text-gray-900">Sign in to AlphaGasIQ</h1>
            <p className="mt-2 text-sm leading-6 text-gray-600">
              AlphaGasIQ is a restricted-access platform. Only authorized users may sign in.
            </p>
          </div>
          <LoginForm />
        </div>
      </div>
    </div>
  );
}
