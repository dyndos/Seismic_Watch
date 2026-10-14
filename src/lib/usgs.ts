/**
 * USGS Earthquake Catalog (ComCat) client — server-side.
 * https://earthquake.usgs.gov/fdsnws/event/1/
 */

import { classifyFault, calcSlipProjection } from "./classifier";
import type { FocalMechanism, QuakeEvent } from "./types";

const BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query";
const FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary";

const TIMEOUT_MS = 25_000;
const MAX_RETRIES = 3;

async function getJson(url: string, params: URLSearchParams): Promise<unknown> {
  let lastErr: unknown = null;
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
      const full = url.includes("?") ? url : `${url}?${params.toString()}`;
      const resp = await fetch(full, { signal: ctrl.signal, cache: "no-store" });
      clearTimeout(t);
      if (!resp.ok) throw new Error(`USGS HTTP ${resp.status}`);
      return await resp.json();
    } catch (e) {
      lastErr = e;
      if (attempt < MAX_RETRIES - 1) {
        await new Promise((r) => setTimeout(r, 2 ** (attempt + 1) * 1000));
      }
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error(String(lastErr));
}

interface UsgsFeature {
  id?: string;
  type?: string;
  properties?: {
    mag?: number | null;
    magType?: string | null;
    place?: string | null;
    time?: number | null;
    updated?: number | null;
    type?: string | null;
    alert?: string | null;
    tsunami?: number | null;
    url?: string | null;
    products?: {
      "moment-tensor"?: MtProduct[];
      "focal-mechanism"?: MtProduct[];
    };
  };
  geometry?: { coordinates?: [number, number, number] };
}

interface MtProduct {
  source?: string;
  properties?: Record<string, string | undefined>;
}

export function parseEvent(feature: UsgsFeature): QuakeEvent {
  const props = feature.properties ?? {};
  const coords = feature.geometry?.coordinates ?? [0, 0, 0];
  return {
    id: feature.id ?? "unknown",
    magnitude: props.mag ?? null,
    magType: props.magType ?? null,
    place: props.place ?? "Unknown",
    time: props.time ? new Date(props.time).toISOString() : new Date().toISOString(),
    longitude: coords[0] ?? 0, // GeoJSON: lon FIRST
    latitude: coords[1] ?? 0,
    depthKm: coords[2] ?? null,
    tsunami: !!props.tsunami,
    alert: props.alert ?? null,
    url: props.url ?? null,
    source: "usgs",
  };
}

export interface CatalogQuery {
  starttime: string; // ISO or YYYY-MM-DD
  endtime: string;
  minmagnitude?: number;
  latitude?: number;
  longitude?: number;
  maxradiuskm?: number;
  limit?: number;
}

export async function fetchCatalog(q: CatalogQuery): Promise<QuakeEvent[]> {
  const params = new URLSearchParams({
    format: "geojson",
    starttime: q.starttime,
    endtime: q.endtime,
    minmagnitude: String(q.minmagnitude ?? 4.5),
    orderby: "time",
    limit: String(q.limit ?? 2000),
  });
  if (q.latitude !== undefined && q.longitude !== undefined) {
    params.set("latitude", String(q.latitude));
    params.set("longitude", String(q.longitude));
    if (q.maxradiuskm) params.set("maxradiuskm", String(q.maxradiuskm));
  }
  const data = (await getJson(BASE_URL, params)) as { features?: UsgsFeature[] };
  return (data.features ?? []).map(parseEvent);
}

export async function fetchFeed(feedName = "4.5_week.geojson"): Promise<QuakeEvent[]> {
  const data = (await getJson(`${FEED_URL}/${feedName}`, new URLSearchParams())) as {
    features?: UsgsFeature[];
  };
  return (data.features ?? []).map(parseEvent);
}

/** Single-event query returns a bare Feature (NOT a FeatureCollection). */
export async function fetchEventDetail(usgsId: string): Promise<UsgsFeature | null> {
  const params = new URLSearchParams({ eventid: usgsId, format: "geojson" });
  const data = (await getJson(BASE_URL, params)) as UsgsFeature & { features?: UsgsFeature[] };
  if (data?.type === "Feature") return data;
  if (Array.isArray(data?.features) && data.features.length > 0) return data.features[0];
  return null;
}

function fnum(v: string | undefined): number | null {
  if (v === undefined || v === null) return null;
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
}

/** Extract and enrich the moment tensor / focal mechanism products. */
export function extractMomentTensor(detail: UsgsFeature | null): FocalMechanism | null {
  if (!detail?.properties?.products) return null;
  const products = detail.properties.products;
  const list = products["moment-tensor"] ?? products["focal-mechanism"];
  if (!list || list.length === 0) return null;
  const mt = list[0];
  const p = mt.properties ?? {};

  const np1Strike = fnum(p["nodal-plane-1-strike"]);
  const np1Dip = fnum(p["nodal-plane-1-dip"]);
  const np1Rake = fnum(p["nodal-plane-1-rake"]);

  return {
    np1Strike,
    np1Dip,
    np1Rake,
    np2Strike: fnum(p["nodal-plane-2-strike"]),
    np2Dip: fnum(p["nodal-plane-2-dip"]),
    np2Rake: fnum(p["nodal-plane-2-rake"]),
    scalarMoment: fnum(p["scalar-moment"]),
    pctDoubleCouple: fnum(p["percent-double-couple"]),
    faultType: classifyFault(np1Rake),
    slipAzimuth: calcSlipProjection(np1Strike, np1Dip, np1Rake),
    compressionAzimuth:
      np1Dip !== null && np1Strike !== null
        ? Math.round(((np1Strike + 90) % 360) * 10) / 10
        : null,
    tensorSource: mt.source ?? "unknown",
  };
}
