/**
 * Seismological models.
 *
 * 1. Reasenberg–Jones aftershock forecast (generic parameters, R&J 1989 /
 *    Page et al. update). λ(t,M) = 10^(a + b·(Mm − M)) · (t + c)^(−p)
 * 2. Regional historical statistics.
 *
 * Every expectation value is paired with a Poisson probability P(≥1) =
 * 1 − exp(−N) — this is what answers "что значат значения вроде 913.7".
 */

import { poissonProb } from "./geo";
import type {
  AftershockForecast,
  AftershockWindow,
  HistStats,
  QuakeEvent,
} from "./types";

export const RJ_DEFAULTS = { a: -1.67, b: 0.91, c: 0.05, p: 1.08 };

/** Analytical integral of modified Omori: expected count in [tStart, tEnd] days. */
export function rjExpectedCount(
  mainMag: number,
  minMag: number,
  tStart: number,
  tEnd: number,
  params = RJ_DEFAULTS,
): number {
  const { a, b, c, p } = params;
  const productivity = 10 ** (a + b * (mainMag - minMag));
  let integral: number;
  if (Math.abs(p - 1) < 1e-6) {
    integral = Math.log(tEnd + c) - Math.log(tStart + c);
  } else {
    integral = ((tEnd + c) ** (1 - p) - (tStart + c) ** (1 - p)) / (1 - p);
  }
  return Math.max(0, productivity * integral);
}

const WINDOWS: [string, number][] = [
  ["1 день", 1],
  ["7 дней", 7],
  ["30 дней", 30],
  ["1 год", 365],
];
const THRESHOLDS = [3, 4, 5, 6];

export function aftershockForecast(mainMag: number): AftershockForecast {
  const windows: AftershockWindow[] = WINDOWS.map(([label, days]) => {
    const cells: AftershockWindow["cells"] = {};
    for (const m of THRESHOLDS) {
      if (m >= mainMag) {
        cells[`M${m}`] = { expected: null, probability: null };
      } else {
        const expected = rjExpectedCount(mainMag, m, 0, days);
        cells[`M${m}`] = {
          expected: Math.round(expected * 10) / 10,
          probability: Math.min(1, poissonProb(expected)),
        };
      }
    }
    return { label, days, cells };
  });
  return { model: "Reasenberg–Jones", params: RJ_DEFAULTS, mainMag, windows };
}

/** Historical statistics of events in the same region before the trigger. */
export function computeHistoryStats(
  events: QuakeEvent[],
  triggerTime: string,
  years = 20,
  radiusKm = 500,
  minMag = 5.0,
): HistStats {
  const bins = [
    { label: "M 5.0–5.9", min: 5.0, max: 6.0, count: 0 },
    { label: "M 6.0–6.9", min: 6.0, max: 7.0, count: 0 },
    { label: "M 7.0–7.9", min: 7.0, max: 8.0, count: 0 },
    { label: "M 8.0+", min: 8.0, max: Infinity, count: 0 },
  ];
  let maxMag: number | null = null;
  let maxEvent: HistStats["maxEvent"] = null;
  let recent12m = 0;
  const tTrig = new Date(triggerTime).getTime();
  const t12m = tTrig - 365 * 24 * 3600 * 1000;

  for (const e of events) {
    const m = e.magnitude ?? 0;
    if (m < minMag) continue;
    const bin = bins.find((b) => m >= b.min && m < b.max);
    if (bin) bin.count++;
    if (maxMag === null || m > maxMag) {
      maxMag = m;
      maxEvent = { id: e.id, place: e.place, time: e.time, magnitude: m };
    }
    const t = new Date(e.time).getTime();
    if (t >= t12m && t < tTrig) recent12m++;
  }

  const total = bins.reduce((s, b) => s + b.count, 0);
  return {
    years,
    radiusKm,
    minMag,
    total,
    bins: bins.map(({ label, count }) => ({ label, count })),
    maxMag,
    maxEvent,
    annualRate: Math.round((total / years) * 100) / 100,
    recent12m,
  };
}
