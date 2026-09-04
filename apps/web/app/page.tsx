import Link from "next/link";

/**
 * Public marketing landing page. Deliberately has no header/sidebar chrome from
 * `components/header/HeaderBar.tsx` (that's the authenticated platform's market-data
 * header) — this page is reachable by anyone, unauthenticated, and must never imply
 * self-service signup exists. There is no Request Access / Create Account CTA
 * anywhere on this page by design (see docs/access-model.md "No Self-Registration").
 *
 * "Platform" / "Intelligence" / "AI Agents" / "Risk & Governance" / "About" are
 * in-page anchors rather than separate routes for this first milestone — the nav
 * items the spec calls out map cleanly onto sections of one page; only "Contact" and
 * "Client Login" need their own routes (`/contact`, `/login`).
 */

const NAV_LINKS = [
  { href: "#platform", label: "Platform" },
  { href: "#intelligence", label: "Intelligence" },
  { href: "#agents", label: "AI Agents" },
  { href: "#governance", label: "Risk & Governance" },
  { href: "#about", label: "About" },
  { href: "/contact", label: "Contact" },
];

const INTELLIGENCE_COVERAGE = [
  { title: "Market Data", body: "Henry Hub and forward-curve pricing, continuously normalized and classified by source." },
  { title: "Weather", body: "ECMWF/GFS model comparisons translated into heating- and cooling-demand deltas." },
  { title: "Storage", body: "Weekly EIA storage forecasts benchmarked against market consensus." },
  { title: "Production", body: "Lower-48 dry gas production and basin-level supply tracking." },
  { title: "Pipelines", body: "A live digital twin of major corridors, interconnects, and constrained capacity." },
  { title: "LNG", body: "Feedgas demand, terminal utilization, and netback economics." },
  { title: "Power Markets", body: "ISO/RTO natural-gas-fueled generation and power-burn demand." },
  { title: "News & Events", body: "Structured event detection with supply/demand impact estimates and citations." },
  { title: "Quantitative Models", body: "Point-in-time-correct forecasting, regime detection, and walk-forward backtesting." },
  { title: "Portfolio Risk", body: "Exposure, VaR, drawdown, and concentration monitored against hard limits." },
];

const HOW_IT_WORKS = [
  "External Market Data",
  "Data & Intelligence Fabric",
  "Specialized AI Agents",
  "Chief Trading Agent",
  "AI Investment Committee",
  "Independent Risk Governor",
  "Human Decision Maker",
  "Paper Execution / Portfolio Monitoring",
];

const AI_ORGANIZATION = [
  { name: "Chief Trading Agent", body: "Coordinates the research cycle and synthesizes a single market view from every team below." },
  { name: "Fundamental Research Agents", body: "Supply, demand, storage, weather, and pipeline specialists." },
  { name: "Market Intelligence Agents", body: "Real-time market data and news/event detection." },
  { name: "Quantitative Research Agents", body: "Forecasting, regime detection, relative value, and backtesting." },
  { name: "Strategy Agents", body: "Translate research into a proposed directional or relative-value thesis." },
  { name: "AI Investment Committee", body: "Bull, Bear, Skeptic, Data Integrity, and Portfolio agents debate every thesis." },
  { name: "Independent Risk Governor", body: "A deterministic, non-LLM control with absolute veto authority — never bypassed." },
];

const GOVERNANCE_POINTS = [
  "Invitation-only access — every account is provisioned by an authorized administrator",
  "Role-based permissions and feature-level entitlements enforced server-side",
  "Secure Magic Link authentication — no passwords to phish or leak",
  "Full audit logging of every sensitive administrative action",
  "Complete data lineage from source to recommendation",
  "An independent, deterministic Risk Governor no AI agent can modify or override",
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-elavo-navy text-white">
      <SiteHeader />
      <Hero />
      <PlatformOverview />
      <HowItWorks />
      <IntelligenceCoverage />
      <AiOrganization />
      <Governance />
      <About />
      <SiteFooter />
    </div>
  );
}

function SiteHeader() {
  return (
    <header className="sticky top-0 z-10 border-b border-white/10 bg-elavo-navy/95 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold tracking-tight">AlphaGasIQ</span>
          <span className="text-[10px] text-white/50">Powered by Elavo AI</span>
        </div>
        <nav className="hidden items-center gap-6 text-xs uppercase tracking-wide text-white/70 md:flex">
          {NAV_LINKS.map((link) => (
            <Link key={link.href} href={link.href} className="hover:text-elavo-blueLight">
              {link.label}
            </Link>
          ))}
        </nav>
        <Link
          href="/login"
          className="rounded border border-elavo-blue px-3 py-1.5 text-xs font-medium text-elavo-blueLight hover:bg-elavo-blue hover:text-white"
        >
          Client Login
        </Link>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden border-b border-white/10 px-6 py-24">
      <NetworkMotif />
      <div className="relative mx-auto max-w-3xl text-center">
        <p className="mb-4 text-[11px] uppercase tracking-[0.2em] text-elavo-blueLight">
          Private, invitation-only institutional platform
        </p>
        <h1 className="text-4xl font-semibold leading-tight tracking-tight md:text-5xl">
          Agentic Intelligence for Natural Gas Markets
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-sm leading-relaxed text-white/70 md:text-base">
          AlphaGasIQ combines real-time market data, natural gas fundamentals, weather
          intelligence, pipeline information, LNG activity, power markets, news, and
          quantitative models with specialized AI agents to identify and evaluate natural
          gas market opportunities — with an independent risk function and a human
          decision maker always in the loop.
        </p>
        <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
          <Link
            href="/login"
            className="rounded bg-elavo-blue px-6 py-2.5 text-sm font-medium text-white hover:bg-elavo-blueLight"
          >
            Client Login
          </Link>
          <Link
            href="#platform"
            className="rounded border border-white/20 px-6 py-2.5 text-sm font-medium text-white/80 hover:border-elavo-blueLight hover:text-elavo-blueLight"
          >
            Learn More
          </Link>
          <Link href="/contact" className="text-sm font-medium text-white/50 hover:text-white/80">
            Contact Us
          </Link>
        </div>
        <p className="mt-8 text-[11px] text-white/40">
          Platform access is provisioned directly to authorized users and institutional partners.
        </p>
      </div>
    </section>
  );
}

/** Dependency-free inline-SVG network motif — no external imagery/asset pipeline,
 * consistent with the rest of this codebase's approach to graphics (see
 * components/pipeline-map). Purely decorative; aria-hidden. */
function NetworkMotif() {
  const nodes = [
    [40, 60], [180, 30], [340, 80], [480, 40], [620, 90],
    [100, 160], [260, 190], [420, 150], [560, 200],
  ];
  const edges = [
    [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [1, 6], [2, 6], [3, 7], [4, 8], [5, 6], [6, 7], [7, 8],
  ];
  return (
    <svg
      aria-hidden
      className="pointer-events-none absolute inset-0 h-full w-full opacity-[0.15]"
      viewBox="0 0 660 220"
      preserveAspectRatio="xMidYMid slice"
    >
      {edges.map(([a, b], i) => (
        <line
          key={i}
          x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]}
          stroke="#2f6fed" strokeWidth="1"
        />
      ))}
      {nodes.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 4 : 2.5} fill="#6b9bff" />
      ))}
    </svg>
  );
}

function SectionHeading({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className="mb-10 text-center">
      <p className="text-[11px] uppercase tracking-[0.2em] text-elavo-blueLight">{eyebrow}</p>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight md:text-3xl">{title}</h2>
    </div>
  );
}

function PlatformOverview() {
  const points = [
    ["Real-time natural gas intelligence", "Continuously refreshed market, fundamentals, and event data with visible freshness and lineage."],
    ["Specialized AI agents", "A multi-agent organization, not a single monolithic model — each agent has a narrow, auditable mandate."],
    ["Quantitative forecasting", "Point-in-time-correct forecasting and walk-forward-validated models, judged only on evidence."],
    ["Natural Gas Digital Twin", "A graph-based model of production basins, processing, storage, LNG terminals, and pipeline corridors."],
    ["Trading strategy analysis", "Every thesis is debated by a Bull, Bear, and Skeptic agent before it reaches a human."],
    ["Independent risk controls", "A deterministic Risk Governor with absolute veto authority, structurally outside any LLM's control."],
    ["Human + AI decision making", "AI proposes and evaluates; a human authorizes every position."],
    ["Portfolio analytics", "Exposure, P&L, and risk monitored continuously against configured limits."],
    ["Data lineage and auditability", "Every recommendation traces back to its source data, model version, and reasoning summary."],
  ];
  return (
    <section id="platform" className="border-b border-white/10 px-6 py-20">
      <div className="mx-auto max-w-5xl">
        <SectionHeading eyebrow="Platform" title="An AI-native natural gas intelligence organization" />
        <div className="grid gap-6 md:grid-cols-3">
          {points.map(([title, body]) => (
            <div key={title} className="rounded border border-white/10 bg-white/[0.02] p-5">
              <h3 className="text-sm font-medium text-white">{title}</h3>
              <p className="mt-2 text-xs leading-relaxed text-white/60">{body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function HowItWorks() {
  return (
    <section className="border-b border-white/10 px-6 py-20">
      <div className="mx-auto max-w-2xl">
        <SectionHeading eyebrow="How it works" title="From raw data to an authorized decision" />
        <ol className="relative">
          {HOW_IT_WORKS.map((step, i) => (
            <li key={step} className="relative flex items-start gap-4 pb-8 last:pb-0">
              {i < HOW_IT_WORKS.length - 1 && (
                <span className="absolute left-[15px] top-8 h-full w-px bg-elavo-blue/30" aria-hidden />
              )}
              <span className="z-[1] flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-elavo-blue bg-elavo-navy text-xs font-medium text-elavo-blueLight">
                {i + 1}
              </span>
              <span className="pt-1.5 text-sm text-white/80">{step}</span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function IntelligenceCoverage() {
  return (
    <section id="intelligence" className="border-b border-white/10 px-6 py-20">
      <div className="mx-auto max-w-5xl">
        <SectionHeading eyebrow="Intelligence coverage" title="Every input that moves the natural gas market" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {INTELLIGENCE_COVERAGE.map((card) => (
            <div key={card.title} className="rounded border border-white/10 bg-white/[0.02] p-4">
              <h3 className="text-xs font-medium uppercase tracking-wide text-elavo-blueLight">{card.title}</h3>
              <p className="mt-2 text-xs leading-relaxed text-white/60">{card.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function AiOrganization() {
  return (
    <section id="agents" className="border-b border-white/10 px-6 py-20">
      <div className="mx-auto max-w-4xl">
        <SectionHeading eyebrow="AI trading organization" title="A trading desk, not a chatbot" />
        <div className="grid gap-4 md:grid-cols-2">
          {AI_ORGANIZATION.map((role) => (
            <div key={role.name} className="rounded border border-white/10 bg-white/[0.02] p-5">
              <h3 className="text-sm font-medium text-white">{role.name}</h3>
              <p className="mt-2 text-xs leading-relaxed text-white/60">{role.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Governance() {
  return (
    <section id="governance" className="border-b border-white/10 bg-white/[0.02] px-6 py-20">
      <div className="mx-auto max-w-3xl">
        <SectionHeading eyebrow="Security & governance" title="Built as a controlled institutional system" />
        <ul className="space-y-3">
          {GOVERNANCE_POINTS.map((point) => (
            <li key={point} className="flex items-start gap-3 text-sm text-white/75">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-elavo-blue" aria-hidden />
              {point}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function About() {
  return (
    <section id="about" className="px-6 py-20">
      <div className="mx-auto max-w-2xl text-center">
        <SectionHeading eyebrow="About" title="Powered by Elavo AI" />
        <p className="text-sm leading-relaxed text-white/60">
          AlphaGasIQ is an agentic natural gas intelligence and decision-support platform
          built by Elavo AI. It is a decision-support and paper-trading system — no live
          order routing is enabled. Platform access is provisioned directly to authorized
          users and institutional partners; there is no public signup or self-registration.
        </p>
      </div>
    </section>
  );
}

function SiteFooter() {
  return (
    <footer className="border-t border-white/10 px-6 py-10">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 text-[11px] text-white/40 md:flex-row">
        <span>&copy; {new Date().getFullYear()} AlphaGasIQ — Powered by Elavo AI</span>
        <div className="flex items-center gap-6">
          <Link href="/contact" className="hover:text-white/70">Contact</Link>
          <Link href="/login" className="hover:text-white/70">Client Login</Link>
        </div>
        <span>Decision-support &amp; paper-trading — no live orders are ever routed.</span>
      </div>
    </footer>
  );
}
