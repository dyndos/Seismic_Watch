/** Display formatting helpers (client & server safe). */

export function fmtDateTimeUTC(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const dd = new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(d);
  const tt = new Intl.DateTimeFormat("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
    hour12: false,
  }).format(d);
  return `${dd}, ${tt} UTC`;
}

export function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  }).format(d);
}

export function fmtNum(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n);
}

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(n);
}

export function fmtPct(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return `${fmtNum(n, digits)}%`;
}

/** Visual confidence tier for magnitude. */
export function magTone(mag: number | null | undefined): {
  text: string;
  bg: string;
  ring: string;
} {
  const m = mag ?? 0;
  if (m >= 8) return { text: "text-fuchsia-200", bg: "bg-fuchsia-500/15", ring: "ring-fuchsia-400/40" };
  if (m >= 7) return { text: "text-rose-300", bg: "bg-rose-500/15", ring: "ring-rose-400/40" };
  if (m >= 6) return { text: "text-orange-300", bg: "bg-orange-500/15", ring: "ring-orange-400/40" };
  if (m >= 5) return { text: "text-amber-300", bg: "bg-amber-500/15", ring: "ring-amber-400/40" };
  return { text: "text-emerald-300", bg: "bg-emerald-500/15", ring: "ring-emerald-400/40" };
}

/** Hex color for map markers by magnitude. */
export function magColor(mag: number): string {
  if (mag >= 8) return "#e879f9";
  if (mag >= 7) return "#fb7185";
  if (mag >= 6) return "#fb923c";
  if (mag >= 5) return "#fbbf24";
  return "#34d399";
}
