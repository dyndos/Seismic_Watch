import type { ReactNode } from "react";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ArrowLeftRight,
  MoveDiagonal,
  HelpCircle,
  AlertTriangle,
  type LucideIcon,
} from "lucide-react";
import type { FaultType } from "@/lib/types";
import { FAULT_TYPE_RU } from "@/lib/classifier";
import { magTone } from "@/lib/format";

// ── Section shell ──────────────────────────────────────────────────────────
export function Section({
  id,
  kicker,
  title,
  right,
  children,
}: {
  id: string;
  kicker: string;
  title: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-line-soft pb-4">
        <div>
          <div className="num text-[11px] tracking-[0.3em] text-signal/80 uppercase">{kicker}</div>
          <h2 className="font-display mt-1 text-xl font-semibold text-mist sm:text-2xl">{title}</h2>
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

// ── Key/value stat ─────────────────────────────────────────────────────────
export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="panel-inset px-4 py-3">
      <div className="text-[11px] tracking-wide text-fog uppercase">{label}</div>
      <div className="mt-1 text-lg font-semibold text-mist">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-fog/80">{hint}</div> : null}
    </div>
  );
}

// ── Magnitude badge ────────────────────────────────────────────────────────
export function MagBadge({ mag, size = "md" }: { mag: number | null; size?: "sm" | "md" | "lg" }) {
  const tone = magTone(mag);
  const cls =
    size === "lg"
      ? "px-5 py-2.5 text-3xl"
      : size === "sm"
        ? "px-2 py-0.5 text-sm"
        : "px-3 py-1 text-xl";
  return (
    <span className={`num inline-flex items-baseline gap-1 rounded-xl ring-1 ${tone.bg} ${tone.ring} ${tone.text} ${cls} font-bold`}>
      <span className="text-[0.6em] font-medium opacity-80">M</span>
      {mag === null ? "—" : mag.toFixed(1)}
    </span>
  );
}

// ── Fault type badge ───────────────────────────────────────────────────────
const FAULT_ICONS: Record<FaultType, LucideIcon> = {
  strike_slip: ArrowLeftRight,
  thrust: ArrowUpFromLine,
  normal: ArrowDownToLine,
  oblique: MoveDiagonal,
  unknown: HelpCircle,
};

export function FaultBadge({ type }: { type: FaultType }) {
  const Icon = FAULT_ICONS[type] ?? HelpCircle;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500/10 px-2.5 py-1 text-sm font-medium text-sky-200 ring-1 ring-sky-400/30">
      <Icon className="h-4 w-4" />
      {FAULT_TYPE_RU[type]}
    </span>
  );
}

// ── Disclaimer box ─────────────────────────────────────────────────────────
export function Disclaimer({ text }: { text: string }) {
  return (
    <div className="mt-4 flex gap-3 rounded-xl border border-warn/25 bg-warn/5 px-4 py-3 text-sm leading-relaxed text-amber-200/80">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
      <p>{text}</p>
    </div>
  );
}

// ── Horizontal bar ─────────────────────────────────────────────────────────
export function Bar({
  label,
  count,
  max,
  tone = "bg-sky-400/70",
}: {
  label: string;
  count: number;
  max: number;
  tone?: string;
}) {
  const pct = max > 0 ? Math.max(2, (count / max) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="num w-20 shrink-0 text-right text-xs text-fog">{label}</div>
      <div className="h-5 flex-1 overflow-hidden rounded-md bg-abyss/80 ring-1 ring-line-soft">
        <div className={`h-full rounded-md ${tone}`} style={{ width: `${count === 0 ? 0 : pct}%` }} />
      </div>
      <div className="num w-10 shrink-0 text-sm text-mist">{count}</div>
    </div>
  );
}

// ── Nav ────────────────────────────────────────────────────────────────────
export function Nav({ right }: { right?: ReactNode }) {
  return (
    <header className="sticky top-0 z-40 border-b border-line-soft/80 bg-ink/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-3.5 sm:px-8">
        <a href="/" className="group flex items-center gap-3">
          <span className="relative flex h-9 w-9 items-center justify-center rounded-lg bg-signal/10 ring-1 ring-signal/30">
            <ActivityIcon />
            <span className="animate-pulse-soft absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-signal" />
          </span>
          <span className="font-display text-sm font-bold tracking-[0.25em] text-mist uppercase">
            Seismic<span className="text-signal">Watch</span>
          </span>
        </a>
        <nav className="flex items-center gap-2 text-sm text-fog sm:gap-4">
          <a href="/" className="rounded-lg px-3 py-1.5 transition hover:bg-sky-400/10 hover:text-mist">
            Мониторинг
          </a>
          <a href="/exposure" className="rounded-lg px-3 py-1.5 transition hover:bg-sky-400/10 hover:text-mist">
            Риск городов
          </a>
          {right}
        </nav>
      </div>
    </header>
  );
}

function ActivityIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 text-signal" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 13h3l2-7 3 12 3-9 2 4h7" />
    </svg>
  );
}

// ── Loading shimmer block ──────────────────────────────────────────────────
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-line-soft/40 ${className}`} />;
}
