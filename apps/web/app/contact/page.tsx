import Link from "next/link";
import { ContactForm } from "./ContactForm";

export const metadata = { title: "Contact — AlphaGasIQ" };

export default function ContactPage() {
  return (
    <div className="min-h-screen bg-elavo-navy px-6 py-16 text-white">
      <div className="mx-auto max-w-lg">
        <div className="mb-8 text-center">
          <Link href="/" className="text-sm font-semibold tracking-tight">
            AlphaGasIQ
          </Link>
          <p className="mt-1 text-[10px] text-white/50">Powered by Elavo AI</p>
        </div>
        <h1 className="text-center text-2xl font-semibold tracking-tight">Contact Us</h1>
        <p className="mx-auto mt-3 max-w-md text-center text-xs leading-relaxed text-white/50">
          This form is for general business inquiries only. Submitting this form does not
          create an AlphaGasIQ account or provide platform access. AlphaGasIQ is a private,
          invitation-only platform — accounts are provisioned directly by an authorized
          administrator.
        </p>
        <div className="mt-8 rounded border border-white/10 bg-white/[0.02] p-6">
          <ContactForm />
        </div>
      </div>
    </div>
  );
}
