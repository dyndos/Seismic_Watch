/**
 * Full analysis pipeline orchestrator (server-only).
 *
 * Mirrors the corrected prototype flow:
 *   event → focal mechanism → nearest plate boundary → proximity alerts →
 *   regional history → aftershock forecast → inter-regional statistical
 *   forecast → hindcast validation → factual sequence.
 */

import { createHash } from "crypto";
import { aftershockForecast, computeHistoryStats } from "./models";
import {
  annotateCatalog,
  backtestTrigger,
  buildSequence,
  forecastRemoteActivity,
} from "./regional";
import { nearestBoundaryInfo, platesWithinRadius } from "./boundaries";
import { fetchCatalog, fetchEventDetail, extractMomentTensor, parseEvent } from "./usgs";
import { haversineKm } from "./geo";
import { MAJOR_CITIES, FALLBACK_SITES } from "./data";
import { getSites } from "@/db/bootstrap";
import type {
  AnalysisResult,
  CityHit,
  ManualSpec,
  MapAftershock,
  QuakeEvent,
  SiteHit,
} from "./types";

const DAY = 24 * 3600 * 1000;

/** Bump when the analysis logic changes — invalidates the DB cache. */
export const MODEL_VERSION = 3;

function isoDaysAgo(from: Date, days: number): string {
  return new Date(from.getTime() - days * DAY).toISOString();
}
function isoDaysAhead(from: Date, days: number): string {
  return new Date(from.getTime() + days * DAY).toISOString();
}

export function manualKey(spec: ManualSpec): string {
  const h = createHash("sha256")
    .update(
      [spec.latitude, spec.longitude, spec.magnitude, spec.depthKm ?? 10, spec.faultType ?? ""].join(
        "|",
      ),
    )
    .digest("hex")
    .slice(0, 10);
  return `manual-${h}`;
}

function eventFromManual(spec: ManualSpec, key: string): QuakeEvent {
  return {
    id: key,
    magnitude: spec.magnitude,
    magType: "сценарий",
    place:
      spec.place?.trim() ||
      `Гипотетический сценарий (${spec.latitude.toFixed(2)}, ${spec.longitude.toFixed(2)})`,
    time: new Date().toISOString(),
    latitude: spec.latitude,
    longitude: spec.longitude,
    depthKm: spec.depthKm ?? 10,
    tsunami: false,
    alert: null,
    source: "manual",
  };
}

async function resolveEvent(
  key: string,
  spec?: ManualSpec,
): Promise<{ event: QuakeEvent; focal: ReturnType<typeof extractMomentTensor>; isManual: boolean }> {
  if (key.startsWith("manual-")) {
    if (!spec) throw Object.assign(new Error("Сценарий не найден в кэше — пересоздайте расчёт"), { status: 404 });
    const event = eventFromManual(spec, key);
    let focal: ReturnType<typeof extractMomentTensor> = null;
    if (spec.faultType && spec.faultType !== "unknown") {
      focal = {
        np1Strike: null,
        np1Dip: null,
        np1Rake: null,
        np2Strike: null,
        np2Dip: null,
        np2Rake: null,
        scalarMoment: null,
        pctDoubleCouple: null,
        faultType: spec.faultType,
        slipAzimuth: spec.slipAzimuth ?? null,
        compressionAzimuth: spec.slipAzimuth ?? null,
        tensorSource: "предположение пользователя",
      };
    }
    return { event, focal, isManual: true };
  }
  const detail = await fetchEventDetail(key);
  if (!detail) throw Object.assign(new Error(`Событие ${key} не найдено в каталоге USGS`), { status: 404 });
  return { event: parseEvent(detail), focal: extractMomentTensor(detail), isManual: false };
}

export async function runAnalysis(key: string, spec?: ManualSpec): Promise<AnalysisResult> {
  const { event, focal, isManual } = await resolveEvent(key, spec);
  const tEvent = new Date(event.time);
  const now = new Date();

  const boundary = nearestBoundaryInfo(event.latitude, event.longitude);

  // ── Proximity alerts ──────────────────────────────────────────────
  const dbSites = await getSites().catch(() => null);
  const sitesSrc = dbSites && dbSites.length > 0 ? dbSites : FALLBACK_SITES;
  const nearbySites: SiteHit[] = sitesSrc
    .map((s) => ({
      name: s.name,
      siteType: s.siteType,
      latitude: s.latitude,
      longitude: s.longitude,
      country: "country" in s ? s.country : null,
      contact: "contact" in s ? (s as { contact?: string }).contact ?? null : null,
      distanceKm: Math.round(haversineKm(event.latitude, event.longitude, s.latitude, s.longitude)),
    }))
    .filter((s) => s.distanceKm <= 1500)
    .sort((a, b) => a.distanceKm - b.distanceKm);

  const nearbyCities: CityHit[] = MAJOR_CITIES.map((c) => ({
    name: c.name,
    country: c.country,
    popMillion: c.popMillion,
    lat: c.lat,
    lon: c.lon,
    distanceKm: Math.round(haversineKm(event.latitude, event.longitude, c.lat, c.lon)),
  }))
    .filter((c) => c.distanceKm <= 1000)
    .sort((a, b) => a.distanceKm - b.distanceKm);

  // ── Regional history: 20y, M≥5, 500 km ────────────────────────────
  let history = null;
  try {
    const histEvents = await fetchCatalog({
      starttime: isoDaysAgo(tEvent, 365 * 20),
      endtime: event.time,
      minmagnitude: 5.0,
      latitude: event.latitude,
      longitude: event.longitude,
      maxradiuskm: 500,
      limit: 5000,
    });
    history = computeHistoryStats(histEvents, event.time);
  } catch {
    history = null;
  }

  // ── Aftershock forecast ───────────────────────────────────────────
  const aftershock = (event.magnitude ?? 0) >= 5.0 ? aftershockForecast(event.magnitude!) : null;

  // ── Aftershocks for the map (30d after, or last 30d for old events) ─
  let aftershocks30d: MapAftershock[] = [];
  try {
    const asEnd = new Date(Math.min(tEvent.getTime() + 30 * DAY, now.getTime()));
    const list = await fetchCatalog({
      starttime: new Date(tEvent.getTime() + 60 * 1000).toISOString(),
      endtime: asEnd.toISOString(),
      minmagnitude: 4.0,
      latitude: event.latitude,
      longitude: event.longitude,
      maxradiuskm: 500,
      limit: 1000,
    });
    aftershocks30d = list.map((e) => ({
      id: e.id,
      latitude: e.latitude,
      longitude: e.longitude,
      magnitude: e.magnitude ?? 0,
      depthKm: e.depthKm,
      time: e.time,
      place: e.place,
    }));
  } catch {
    aftershocks30d = [];
  }

  // ── Inter-regional statistical forecast + validation + sequence ────
  let regional = null;
  let validation = null;
  let sequence: ReturnType<typeof buildSequence> = [];

  if ((event.magnitude ?? 0) >= 6.0 && boundary && boundary.plates.length > 0) {
    try {
      // The stressed system = union of plates on all boundary segments within
      // 400 km of the epicenter (a junction, not a single line).
      const systemPlates = platesWithinRadius(event.latitude, event.longitude, 400);
      const trigPlates = systemPlates.length > 0 ? systemPlates : boundary.plates;

      const gStart = isoDaysAgo(tEvent, 365 * 20);
      const gEnd = isManual
        ? isoDaysAhead(now, 1) // manual: full catalog up to now
        : new Date(Math.min(tEvent.getTime() + 450 * DAY, now.getTime())).toISOString();
      const globalCatalog = await fetchCatalog({
        starttime: gStart,
        endtime: gEnd,
        minmagnitude: 6.0,
        limit: 20000,
      });
      const annotated = annotateCatalog(globalCatalog);
      const catalogEnd = now.getTime();

      if (!isManual) {
        regional = forecastRemoteActivity(event, trigPlates, annotated, [3, 6, 12], 6.5, 1000, boundary.name);
        validation = backtestTrigger(event, trigPlates, annotated, catalogEnd, [3, 6, 12], 6.5, 1000, boundary.name);
        sequence = buildSequence(event, trigPlates, annotated);
      } else {
        // For manual scenarios use "now" as t0 analog: statistics unchanged,
        // sequence/validation are skipped by construction.
        regional = forecastRemoteActivity(event, trigPlates, annotated, [3, 6, 12], 6.5, 1000, boundary.name);
      }
    } catch {
      regional = null;
    }
  }

  return {
    key,
    modelVersion: MODEL_VERSION,
    generatedAt: new Date().toISOString(),
    event,
    focal,
    boundary,
    nearbySites,
    nearbyCities,
    history,
    aftershock,
    regional,
    validation,
    sequence,
    aftershocks30d,
    isManual,
  };
}
