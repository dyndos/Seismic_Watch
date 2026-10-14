/**
 * Cross-region stress-propagation analysis (empirical / statistical).
 *
 * Faithful TypeScript port of the prototype's regional_forecast.py, plus:
 *  - strict hindcast validation (training window ends before the trigger),
 *  - factual "sequence after the event" listing with same-system flag,
 *  - partial-horizon awareness for recent events.
 *
 * METHOD: empirical frequency from the historical global catalog (M≥6,
 * ~20 years). NOT a physical Coulomb stress model. Correlation ≠ causation.
 */

import { haversineKm, regionLabel } from "./geo";
import { makePlateAnnotator } from "./boundaries";
import { plateName } from "./data";
import type {
  HorizonResult,
  QuakeEvent,
  RegionalForecast,
  SequenceItem,
  ValidationHorizon,
  ValidationResult,
} from "./types";

export const DAYS_PER_MONTH = 30.44;

export interface AnnotatedEvent extends QuakeEvent {
  t: number; // epoch ms
  plates: string[];
  boundaryName: string;
}

export function annotateCatalog(events: QuakeEvent[]): AnnotatedEvent[] {
  const annotate = makePlateAnnotator();
  const out: AnnotatedEvent[] = [];
  for (const e of events) {
    const t = new Date(e.time).getTime();
    if (!Number.isFinite(t)) continue;
    const ann = annotate(e.latitude, e.longitude);
    out.push({ ...e, t, plates: ann.plates, boundaryName: ann.name });
  }
  out.sort((a, b) => a.t - b.t);
  return out;
}

function monthMs(months: number): number {
  return months * DAYS_PER_MONTH * 24 * 3600 * 1000;
}

export function forecastRemoteActivity(
  trigger: QuakeEvent,
  triggerPlates: string[],
  catalog: AnnotatedEvent[],
  horizonsMonths: number[] = [3, 6, 12],
  minRemoteMag = 6.5,
  minDistanceKm = 1000,
  triggerBoundaryName = "",
): RegionalForecast {
  const trigMag = trigger.magnitude ?? 0;
  // Lower analog threshold: otherwise great events (M7.5+) leave almost no
  // historical sample on a 20-year catalog on smaller plate systems.
  const triggerMinMag = Math.max(6.0, trigMag - 1.5);

  const base: Omit<RegionalForecast, "status" | "results" | "sampleSize" | "topRegions"> = {
    triggerMag: trigMag,
    triggerPlates,
    triggerPlateNames: triggerPlates.map(plateName),
    triggerMinMag,
    minRemoteMag,
    minDistanceKm,
    catalogSize: catalog.length,
  };

  if (triggerPlates.length === 0) {
    return { ...base, status: "no_plates", sampleSize: 0, results: {}, topRegions: [] };
  }
  const plateSet = new Set(triggerPlates);

  const sameSystem = catalog.filter((e) => e.plates.some((p) => plateSet.has(p)));
  const histTriggers = sameSystem.filter((e) => (e.magnitude ?? 0) >= triggerMinMag);

  if (histTriggers.length < 3) {
    return {
      ...base,
      status: "insufficient_data",
      message: `Недостаточно исторических триггеров (найдено ${histTriggers.length}, нужно ≥3) для M≥${triggerMinMag.toFixed(1)} на этой плитной системе.`,
      sampleSize: histTriggers.length,
      results: {},
      topRegions: [],
    };
  }

  const results: Record<string, HorizonResult> = {};
  const regionCounter = new Map<string, number>();
  const midHorizon = horizonsMonths[Math.floor(horizonsMonths.length / 2)];

  for (const h of horizonsMonths) {
    let triggered = 0;
    for (const trig of histTriggers) {
      const tEnd = trig.t + monthMs(h);
      let found = false;
      for (const ev of sameSystem) {
        if (ev.t <= trig.t) continue;
        if (ev.t > tEnd) break;
        if ((ev.magnitude ?? 0) < minRemoteMag) continue;
        // remote activation: far away AND on a different boundary segment,
        // otherwise any busy plate system trivially saturates the metric.
        if (ev.boundaryName && ev.boundaryName === trig.boundaryName) continue;
        if (haversineKm(trig.latitude, trig.longitude, ev.latitude, ev.longitude) >= minDistanceKm) {
          found = true;
          if (h === midHorizon) {
            const r = regionLabel(ev.place);
            regionCounter.set(r, (regionCounter.get(r) ?? 0) + 1);
          }
        }
      }
      if (found) triggered++;
    }
    results[`${h}m`] = {
      months: h,
      triggered,
      total: histTriggers.length,
      percentage: Math.round((triggered / histTriggers.length) * 1000) / 10,
    };
  }

  const topRegions = [...regionCounter.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([region, count]) => ({ region, count }));

  return {
    ...base,
    status: "ok",
    sampleSize: histTriggers.length,
    results,
    topRegions,
  };
}

/**
 * Hindcast validation: replay the model using ONLY data that existed before
 * the trigger (training window excluded the forecast period), then compare
 * with what actually happened.
 */
export function backtestTrigger(
  trigger: QuakeEvent,
  triggerPlates: string[],
  catalog: AnnotatedEvent[],
  catalogEnd: number, // epoch ms of latest catalog data (≈ now)
  horizonsMonths: number[] = [3, 6, 12],
  minRemoteMag = 6.5,
  minDistanceKm = 1000,
  triggerBoundaryName = "",
): ValidationResult {
  const trigMag = trigger.magnitude ?? 0;
  const triggerMinMag = Math.max(6.3, trigMag - 1.4);
  const t0 = new Date(trigger.time).getTime();
  const plateSet = new Set(triggerPlates);

  const sameSystem = catalog.filter((e) => e.plates.some((p) => plateSet.has(p)));

  // Training: triggers whose full 12-month follow window ends strictly before t0
  const histTriggers = sameSystem.filter(
    (e) => (e.magnitude ?? 0) >= triggerMinMag && e.t + monthMs(12) < t0 && e.id !== trigger.id,
  );

  if (histTriggers.length < 3) {
    return {
      status: "insufficient_data",
      message: `Мало исторических аналогов до события (${histTriggers.length}) — валидация невозможна.`,
      trainingYears: 20,
      horizons: [],
      summary: "",
    };
  }

  const maxH = Math.max(...horizonsMonths);
  const horizonSpan = monthMs(maxH);
  const actualCoverage = Math.min(1, Math.max(0, (catalogEnd - t0) / horizonSpan));

  const horizons: ValidationHorizon[] = horizonsMonths.map((h) => {
    // predicted percentage from strictly-historical triggers
    let hits = 0;
    let total = 0;
    for (const trig of histTriggers) {
      const tEnd = trig.t + monthMs(h);
      if (tEnd >= t0) continue; // window would leak past trigger time
      total++;
      let found = false;
      for (const ev of sameSystem) {
        if (ev.t <= trig.t) continue;
        if (ev.t > tEnd) break;
        if ((ev.magnitude ?? 0) < minRemoteMag) continue;
        if (ev.boundaryName && ev.boundaryName === trig.boundaryName) continue;
        if (haversineKm(trig.latitude, trig.longitude, ev.latitude, ev.longitude) >= minDistanceKm) {
          found = true;
          break;
        }
      }
      if (found) hits++;
    }

    // what ACTUALLY happened within h months after the trigger
    const tEndActual = t0 + monthMs(h);
    const coveragePct = Math.round(
      Math.min(100, Math.max(0, ((catalogEnd - t0) / monthMs(h)) * 100)),
    );
    const observedEvents = sameSystem
      .filter(
        (ev) =>
          ev.t > t0 &&
          ev.t <= tEndActual &&
          ev.id !== trigger.id &&
          (ev.magnitude ?? 0) >= minRemoteMag &&
          ev.boundaryName !== triggerBoundaryName &&
          haversineKm(trigger.latitude, trigger.longitude, ev.latitude, ev.longitude) >=
            minDistanceKm,
      )
      .slice(0, 6)
      .map((ev) => ({
        id: ev.id,
        place: regionLabel(ev.place),
        magnitude: ev.magnitude ?? 0,
        daysAfter: Math.round((ev.t - t0) / (24 * 3600 * 1000)),
      }));

    const fullyCovered = coveragePct >= 99;
    const observed: ValidationHorizon["observed"] = !fullyCovered
      ? "pending"
      : observedEvents.length > 0
        ? "yes"
        : "no";

    return {
      months: h,
      predictedPct: total > 0 ? Math.round((hits / total) * 1000) / 10 : 0,
      basedOn: total,
      observed,
      observedEvents,
      coveragePct,
    };
  });

  const full = horizons.filter((h) => h.observed !== "pending");
  const confirmed = full.filter((h) => h.observed === "yes").length;
  const summary =
    full.length === 0
      ? "Горизонты ещё не закрыты — валидация станет доступна позже."
      : `Совпадение с фактом по ${confirmed} из ${full.length} закрытых горизонтов. ` +
        "Одиночная проверка не доказывает качество модели — это иллюстрация " +
        "работы механизма hindcast-валидации.";

  return {
    status: "ok",
    trainingYears: 20,
    horizons,
    summary,
  };
}

/**
 * Factual chain: all significant events (worldwide, M≥threshold) within
 * `months` after the trigger, flagged whether they lie on the same plate
 * system. Answers the "Турция → Марокко → Афганистан → Непал → Япония →
 * Дагестан" style of observation transparently.
 */
export function buildSequence(
  trigger: QuakeEvent,
  triggerPlates: string[],
  catalog: AnnotatedEvent[],
  months = 12,
  minMag = 6.2,
  minDistanceKm = 250,
  limit = 40,
): SequenceItem[] {
  const t0 = new Date(trigger.time).getTime();
  const tEnd = t0 + monthMs(months);
  const plateSet = new Set(triggerPlates);

  return catalog
    .filter(
      (ev) =>
        ev.t > t0 &&
        ev.t <= tEnd &&
        ev.id !== trigger.id &&
        (ev.magnitude ?? 0) >= minMag &&
        haversineKm(trigger.latitude, trigger.longitude, ev.latitude, ev.longitude) >=
          minDistanceKm,
    )
    .slice(0, limit)
    .map((ev) => ({
      id: ev.id,
      time: ev.time,
      magnitude: ev.magnitude ?? 0,
      place: ev.place,
      region: regionLabel(ev.place),
      latitude: ev.latitude,
      longitude: ev.longitude,
      distanceKm: Math.round(
        haversineKm(trigger.latitude, trigger.longitude, ev.latitude, ev.longitude),
      ),
      daysAfter: Math.round((ev.t - t0) / (24 * 3600 * 1000)),
      sameSystem: ev.plates.some((p) => plateSet.has(p)),
      plates: ev.plates.map(plateName),
    }));
}
