import type { NextRequest } from "next/server";
import { fetchCatalog } from "@/lib/usgs";
import { haversineKm } from "@/lib/geo";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

const DAY = 24 * 3600 * 1000;

/**
 * Match a news-style report (magnitude + date + optional coordinates) to the
 * USGS catalog. Port of the prototype's matcher.py scoring.
 */
export async function POST(req: NextRequest) {
  let body: { magnitude?: unknown; date?: unknown; latitude?: unknown; longitude?: unknown };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return Response.json({ error: "Некорректное тело запроса" }, { status: 400 });
  }

  const magnitude = body.magnitude !== undefined && body.magnitude !== null && body.magnitude !== ""
    ? Number(body.magnitude)
    : null;
  const dateStr = typeof body.date === "string" ? body.date : null;
  const lat = body.latitude !== undefined && body.latitude !== null && body.latitude !== ""
    ? Number(body.latitude)
    : null;
  const lon = body.longitude !== undefined && body.longitude !== null && body.longitude !== ""
    ? Number(body.longitude)
    : null;

  if (!dateStr || Number.isNaN(new Date(dateStr).getTime())) {
    return Response.json({ error: "Укажите дату события" }, { status: 400 });
  }
  if (magnitude === null && (lat === null || lon === null)) {
    return Response.json({ error: "Укажите магнитуду или координаты" }, { status: 400 });
  }

  const t = new Date(dateStr).getTime();
  const start = new Date(t - 2 * DAY).toISOString();
  const end = new Date(Math.min(t + 2 * DAY, Date.now())).toISOString();

  const minMag = magnitude !== null ? Math.max(4.0, magnitude - 1.5) : 4.5;
  const maxMag = magnitude !== null ? magnitude + 1.5 : null;

  try {
    const catalog = await fetchCatalog({
      starttime: start,
      endtime: end,
      minmagnitude: minMag,
      latitude: lat ?? undefined,
      longitude: lon ?? undefined,
      maxradiuskm: lat !== null && lon !== null ? 600 : undefined,
      limit: 500,
    });

    const scored = catalog
      .filter((e) => maxMag === null || (e.magnitude ?? 0) <= maxMag)
      .map((e) => {
        const dtHours = Math.abs(new Date(e.time).getTime() - t) / 3600_000;
        const distKm =
          lat !== null && lon !== null
            ? haversineKm(lat, lon, e.latitude, e.longitude)
            : null;
        const magDiff = magnitude !== null && e.magnitude !== null
          ? Math.abs(e.magnitude - magnitude)
          : null;
        const timeScore = dtHours / 48;
        const distScore = distKm !== null ? distKm / 600 : 0;
        const magScore = magDiff !== null ? magDiff / 1.5 : 0;
        const dims = (distKm !== null ? 1 : 0) + (magDiff !== null ? 1 : 0) + 1;
        const score = (timeScore + distScore + magScore) / dims;
        return {
          id: e.id,
          place: e.place,
          time: e.time,
          magnitude: e.magnitude,
          latitude: e.latitude,
          longitude: e.longitude,
          depthKm: e.depthKm,
          dtHours: Math.round(dtHours * 10) / 10,
          distKm: distKm !== null ? Math.round(distKm) : null,
          magDiff,
          score: Math.round(score * 1000) / 1000,
        };
      })
      .sort((a, b) => a.score - b.score)
      .slice(0, 5);

    return Response.json({ ok: true, candidates: scored });
  } catch {
    return Response.json({ error: "Не удалось запросить каталог USGS" }, { status: 502 });
  }
}
