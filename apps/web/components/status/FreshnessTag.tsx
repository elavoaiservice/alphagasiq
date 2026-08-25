export function FreshnessTag({ asOf }: { asOf: string | null | undefined }) {
  if (!asOf) return <span className="text-[10px] text-terminal-muted">no data</span>;
  const date = new Date(asOf);
  const ageSeconds = (Date.now() - date.getTime()) / 1000;
  const stale = ageSeconds > 3600;
  return (
    <span className={`text-[10px] ${stale ? "text-terminal-warn" : "text-terminal-muted"}`}>
      as of {date.toLocaleString()} {stale ? "(stale)" : ""}
    </span>
  );
}
