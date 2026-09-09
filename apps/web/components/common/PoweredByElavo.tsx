/**
 * "Powered by" + the ElavoAI logo mark.
 *
 * The ElavoAI wordmark ("ELAVO" is deep navy) reads on light surfaces only, so
 * on dark backgrounds we set the logo on a small white chip to keep it legible
 * with correct brand colors.
 *
 *  - tone="light"  → logo directly on a light surface (default; e.g. the header)
 *  - tone="dark"   → logo in a white chip on a dark surface (auth pages, landing)
 */
type Tone = "light" | "dark";

export function PoweredByElavo({
  tone = "light",
  logoClassName = "h-4",
  className = "",
}: {
  tone?: Tone;
  logoClassName?: string;
  className?: string;
}) {
  const label = tone === "dark" ? "text-white/60" : "text-terminal-muted";
  const logo = (
    // eslint-disable-next-line @next/next/no-img-element
    <img src="/elavoai-logo.png" alt="Elavo AI" className={`${logoClassName} w-auto`} />
  );
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <span className={`text-[10px] ${label}`}>Powered by</span>
      {tone === "dark" ? (
        <span className="inline-flex items-center rounded-md bg-white px-1.5 py-1">{logo}</span>
      ) : (
        logo
      )}
    </span>
  );
}
