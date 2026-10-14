/**
 * Pure geospatial math (client & server safe).
 */

export function haversineKm(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const R = 6371.0;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(p1) * Math.cos(p2) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.asin(Math.sqrt(a));
}

/** Cheap squared planar distance (deg², lon scaled by cos(lat)) — for fast scans. */
export function planar2(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const dLat = lat2 - lat1;
  const dLon = (lon2 - lon1) * Math.cos(((lat1 + lat2) / 2) * (Math.PI / 180));
  return dLat * dLat + dLon * dLon;
}

/** Destination point from start, azimuth (deg clockwise from North), distance km. */
export function destinationPoint(
  lat: number,
  lon: number,
  azimuthDeg: number,
  distKm: number,
): [number, number] {
  const R = 6371.0;
  const d = distKm / R;
  const brng = (azimuthDeg * Math.PI) / 180;
  const lat1 = (lat * Math.PI) / 180;
  const lon1 = (lon * Math.PI) / 180;
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brng),
  );
  const lon2 =
    lon1 +
    Math.atan2(
      Math.sin(brng) * Math.sin(d) * Math.cos(lat1),
      Math.cos(d) - Math.sin(lat1) * Math.sin(lat2),
    );
  return [(lat2 * 180) / Math.PI, ((lon2 * 180) / Math.PI + 540) % 360 - 180];
}

export function regionLabel(place: string | null | undefined): string {
  if (!place) return "Unknown region";
  if (place.includes(",")) return place.split(",").pop()!.trim();
  if (place.includes(" of ")) return place.split(" of ").pop()!.trim();
  return place;
}

/** P(>=1 event) under Poisson with expected count n. */
export function poissonProb(expected: number): number {
  return 1 - Math.exp(-expected);
}
