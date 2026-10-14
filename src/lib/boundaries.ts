/**
 * Server-only: load tectonic plate boundaries (PB2002) from the bundled
 * GeoJSON, build a flat point index and answer "nearest boundary" queries.
 */

import fs from "fs";
import path from "path";
import { haversineKm, planar2 } from "./geo";
import { plateName } from "./data";
import type { BoundaryInfo } from "./types";

export interface PlateFeature {
  name: string;
  plateA: string;
  plateB: string;
  type: string | null;
  coords: [number, number][]; // [lat, lon]
}

export interface FlatPoint {
  lat: number;
  lon: number;
  name: string;
  plates: string[];
  type: string | null;
}

let featuresCache: PlateFeature[] | null = null;
let flatCache: FlatPoint[] | null = null;

export function loadBoundaries(): PlateFeature[] {
  if (featuresCache) return featuresCache;
  const file = path.join(process.cwd(), "public", "data", "plates.geojson");
  const raw = JSON.parse(fs.readFileSync(file, "utf8")) as {
    features: {
      properties: { Name?: string; PlateA?: string; PlateB?: string; Type?: string };
      geometry: { type: string; coordinates: number[][] | number[][][] };
    }[];
  };

  const out: PlateFeature[] = [];
  for (const f of raw.features) {
    const props = f.properties ?? {};
    const geom = f.geometry;
    if (!geom) continue;
    const lines: number[][][] =
      geom.type === "MultiLineString"
        ? (geom.coordinates as number[][][])
        : [geom.coordinates as number[][]];
    for (const line of lines) {
      const coords: [number, number][] = line.map((c) => [c[1], c[0]]); // -> [lat, lon]
      if (coords.length < 2) continue;
      out.push({
        name: props.Name ?? "Unknown",
        plateA: props.PlateA ?? "",
        plateB: props.PlateB ?? "",
        type: props.Type || null,
        coords,
      });
    }
  }
  featuresCache = out;
  return out;
}

/** Flatten feature paths into points (downsampled every 2nd point for speed). */
export function buildFlatIndex(features: PlateFeature[] = loadBoundaries()): FlatPoint[] {
  if (flatCache) return flatCache;
  const idx: FlatPoint[] = [];
  for (const f of features) {
    const plates = [f.plateA, f.plateB].filter(Boolean);
    for (let i = 0; i < f.coords.length; i += 2) {
      idx.push({ lat: f.coords[i][0], lon: f.coords[i][1], name: f.name, plates, type: f.type });
    }
    // always include last point
    const last = f.coords[f.coords.length - 1];
    idx.push({ lat: last[0], lon: last[1], name: f.name, plates, type: f.type });
  }
  flatCache = idx;
  return idx;
}

/** Approx nearest-boundary point search using planar metric, refined by haversine. */
export function nearestBoundaryInfo(lat: number, lon: number): BoundaryInfo | null {
  const idx = buildFlatIndex();
  let best: FlatPoint | null = null;
  let bestPlanar = Infinity;
  for (const p of idx) {
    // cheap lon-wrap prefilter
    const dLon0 = Math.abs(p.lon - lon);
    if (dLon0 > 60) continue;
    const d2 = planar2(lat, lon, p.lat, p.lon);
    if (d2 < bestPlanar) {
      bestPlanar = d2;
      best = p;
    }
  }
  if (!best) {
    // fallback global scan (near antimeridian)
    for (const p of idx) {
      const d2 = planar2(lat, lon, p.lat, p.lon);
      if (d2 < bestPlanar) {
        bestPlanar = d2;
        best = p;
      }
    }
  }
  if (!best) return null;
  return {
    distanceKm: Math.round(haversineKm(lat, lon, best.lat, best.lon) * 10) / 10,
    name: best.name,
    plates: best.plates,
    plateNames: best.plates.map(plateName),
    boundaryType: best.type,
  };
}

/**
 * Union of plate codes on ALL boundary segments within `radiusKm` of a point.
 * A strong event stresses the whole junction of boundaries, not only the
 * single nearest line — e.g. Kahramanmaras 2023 loads AT/AR and the
 * Cyprus-arc AF segments alike, which is how the chain reaches Morocco (AF).
 */
export function platesWithinRadius(lat: number, lon: number, radiusKm = 400): string[] {
  const idx = buildFlatIndex();
  const limit = (radiusKm / 111) ** 2; // rough planar limit in deg²
  const found = new Map<string, number>(); // plate code -> min planar dist
  for (const p of idx) {
    const dLon0 = Math.abs(p.lon - lon);
    if (dLon0 > 60) continue;
    const d2 = planar2(lat, lon, p.lat, p.lon);
    if (d2 > limit * 1.21) continue; // cos-lat safety margin
    for (const code of p.plates) {
      const prev = found.get(code);
      if (prev === undefined || d2 < prev) found.set(code, d2);
    }
  }
  return [...found.keys()].sort();
}

/** Find nearest boundary name+plates for many points with rounding cache. */
export function makePlateAnnotator() {
  const idx = buildFlatIndex();
  const cache = new Map<string, { name: string; plates: string[] }>();
  return (lat: number, lon: number): { name: string; plates: string[] } => {
    const key = `${lat.toFixed(1)},${lon.toFixed(1)}`;
    const hit = cache.get(key);
    if (hit) return hit;
    let best: FlatPoint | null = null;
    let bestD2 = Infinity;
    for (const p of idx) {
      const dLon0 = Math.abs(p.lon - lon);
      if (dLon0 > 60) continue;
      const d2 = planar2(lat, lon, p.lat, p.lon);
      if (d2 < bestD2) {
        bestD2 = d2;
        best = p;
      }
    }
    if (!best) {
      for (const p of idx) {
        const d2 = planar2(lat, lon, p.lat, p.lon);
        if (d2 < bestD2) {
          bestD2 = d2;
          best = p;
        }
      }
    }
    const val = { name: best?.name ?? "", plates: best?.plates ?? [] };
    cache.set(key, val);
    return val;
  };
}
