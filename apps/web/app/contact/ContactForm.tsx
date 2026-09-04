"use client";

import { useState } from "react";
import { apiPost } from "@/lib/api-client";

const INQUIRY_TYPES = [
  { value: "GENERAL", label: "General Inquiry" },
  { value: "SALES", label: "Sales" },
  { value: "PARTNERSHIP", label: "Partnership" },
  { value: "MEDIA", label: "Media" },
  { value: "SUPPORT", label: "Support" },
  { value: "OTHER", label: "Other" },
];

const initialForm = {
  first_name: "",
  last_name: "",
  business_email: "",
  company_name: "",
  job_title: "",
  phone: "",
  inquiry_type: "GENERAL",
  message: "",
};

export function ContactForm() {
  const [form, setForm] = useState(initialForm);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function update<K extends keyof typeof initialForm>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await apiPost("/contact", {
        ...form,
        job_title: form.job_title || null,
        phone: form.phone || null,
      });
      setSubmitted(true);
    } catch {
      setError("We couldn't submit your inquiry. Please try again or email us directly.");
    } finally {
      setLoading(false);
    }
  }

  if (submitted) {
    return (
      <div className="rounded border border-elavo-blue/40 bg-elavo-blue/10 p-5 text-sm text-white/85">
        Thank you for contacting AlphaGasIQ. Our team will respond to your inquiry shortly.
      </div>
    );
  }

  const inputClass =
    "w-full rounded border border-white/15 bg-white/[0.03] px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-elavo-blue focus:outline-none";
  const labelClass = "mb-1 block text-xs uppercase tracking-wide text-white/50";

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass}>First Name</label>
          <input required className={inputClass} value={form.first_name} onChange={(e) => update("first_name", e.target.value)} />
        </div>
        <div>
          <label className={labelClass}>Last Name</label>
          <input required className={inputClass} value={form.last_name} onChange={(e) => update("last_name", e.target.value)} />
        </div>
      </div>
      <div>
        <label className={labelClass}>Business Email</label>
        <input required type="email" className={inputClass} value={form.business_email} onChange={(e) => update("business_email", e.target.value)} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass}>Company Name</label>
          <input required className={inputClass} value={form.company_name} onChange={(e) => update("company_name", e.target.value)} />
        </div>
        <div>
          <label className={labelClass}>Job Title</label>
          <input className={inputClass} value={form.job_title} onChange={(e) => update("job_title", e.target.value)} />
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass}>Phone</label>
          <input className={inputClass} value={form.phone} onChange={(e) => update("phone", e.target.value)} />
        </div>
        <div>
          <label className={labelClass}>Inquiry Type</label>
          <select className={inputClass} value={form.inquiry_type} onChange={(e) => update("inquiry_type", e.target.value)}>
            {INQUIRY_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div>
        <label className={labelClass}>Message</label>
        <textarea
          required
          rows={5}
          className={inputClass}
          value={form.message}
          onChange={(e) => update("message", e.target.value)}
        />
      </div>
      {error && <p className="text-xs text-terminal-bear">{error}</p>}
      <button
        type="submit"
        disabled={loading}
        className="w-full rounded bg-elavo-blue py-2.5 text-sm font-medium text-white hover:bg-elavo-blueLight disabled:cursor-not-allowed disabled:opacity-50"
      >
        {loading ? "Sending…" : "Send Inquiry"}
      </button>
    </form>
  );
}
