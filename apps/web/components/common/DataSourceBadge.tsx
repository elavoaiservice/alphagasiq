const COLORS: Record<string, string> = {
  PUBLIC: "text-terminal-bull border-terminal-bull/40",
  LICENSED: "text-terminal-warn border-terminal-warn/40",
  USER_PROVIDED: "text-terminal-accent border-terminal-accent/40",
  SIMULATED: "text-terminal-muted border-terminal-muted/40",
};

export function DataSourceBadge({ classification }: { classification: string }) {
  const cls = COLORS[classification] ?? COLORS.SIMULATED;
  return (
    <span className={`inline-block px-1.5 py-0.5 text-[10px] uppercase tracking-wide border rounded ${cls}`}>
      {classification}
    </span>
  );
}
