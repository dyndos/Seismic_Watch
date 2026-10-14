import type { NextRequest } from "next/server";
import { sql } from "drizzle-orm";
import { db } from "@/db";
import { ensureSchema } from "@/db/bootstrap";
import { nearestBoundaryInfo } from "@/lib/boundaries";
import { fetchCatalog } from "@/lib/usgs";
import { haversineKm, poissonProb, regionLabel } from "@/lib/geo";
import { MAJOR_CITIES } from "@/lib/data";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

const DAY = 24 * 3600 * 1000;
const CACHE_TTL = 24 * 3600 * 1000;

function tierFrom(lambda5: number, maxMag: number) {
  if (lambda5 >= 1 || maxMag >= 7.5)
    return { tier: 4, label: "Очень высокая сейсмичность", color: "rose" };
  if (lambda5 >= 0.3 || maxMag >= 6.5) return { tier: 3, label: "Высокая сейсмичность", color: "orange" };
  if (lambda5 >= 0.1 || maxMag >= 5.5) return { tier: 2, label: "Умеренная сейсмичность", color: "amber" };
  return { tier: 1, label: "Низкая сейсмичность", color: "emerald" };
}

const ADVICE: Record<number, string[]> = {
  4: [
    "Командировки — только с обязательным предвыездным брифингом по действиям при землетрясении",
    "Проверить сейсмостойкость объектов размещения и контрактные условия страхования",
    "Держать под наблюдением региональный прогноз после каждого события M≥6.5 в системе плиты",
  ],
  3: [
    "Рекомендован предвыездный брифинг и проверка планов эвакуации в месте командировки",
    "Контролировать оповещения системы после крупных событий на той же плитной системе",
  ],
  2: [
    "Стандартные меры: знать план эвакуации здания, сильные толчки редки, но возможны",
    "При размещении производства — перепроверить расчётную сейсмичность площадки",
  ],
  1: ["Существенных ограничений нет; базовые меры безопасности"],
};

async function computeExposure(cityName: string) {
  const city = MAJOR_CITIES.find((c) => c.name.toLowerCase() === cityName.toLowerCase());
  if (!city) return null;
  const now = new Date();

  const boundary = nearestBoundaryInfo(city.lat, city.lon);

  const [hist, recent, globalRecent] = await Promise.allSettled([
    fetchCatalog({
      starttime: new Date(now.getTime() - 365 * 30 * DAY).toISOString(),
      endtime: now.toISOString(),
      minmagnitude: 5.0,
      latitude: city.lat,
      longitude: city.lon,
      maxradiuskm: 400,
      limit: 5000,
    }),
    fetchCatalog({
      starttime: new Date(now.getTime() - 365 * DAY).toISOString(),
      endtime: now.toISOString(),
      minmagnitude: 4.0,
      latitude: city.lat,
      longitude: city.lon,
      maxradiuskm: 300,
      limit: 300,
    }),
    fetchCatalog({
      starttime: new Date(now.getTime() - 365 * DAY).toISOString(),
      endtime: now.toISOString(),
      minmagnitude: 6.5,
      limit: 500,
    }),
  ]);

  const histEvents = hist.status === "fulfilled" ? hist.value : [];
  const recentEvents = recent.status === "fulfilled" ? recent.value : [];
  const globalEvents = globalRecent.status === "fulfilled" ? globalRecent.value : [];

  let maxMag = 0;
  let maxEvent: { id: string; place: string; time: string; magnitude: number } | null = null;
  let m6 = 0;
  const byMag = [
    { label: "M 5.0–5.9", count: 0 },
    { label: "M 6.0–6.9", count: 0 },
    { label: "M 7.0+", count: 0 },
  ];
  for (const e of histEvents) {
    const m = e.magnitude ?? 0;
    if (m >= 7) byMag[2].count++;
    else if (m >= 6) {
      byMag[1].count++;
      m6++;
    } else byMag[0].count++;
    if (m > maxMag) {
      maxMag = m;
      maxEvent = { id: e.id, place: e.place, time: e.time, magnitude: m };
    }
  }

  const lambda5 = histEvents.length / 30;
  const lambda6 = m6 / 30;
  const plateSet = new Set(boundary?.plates ?? []);

  const activeTriggers = globalEvents
    .map((e) => ({
      id: e.id,
      place: e.place,
      region: regionLabel(e.place),
      time: e.time,
      magnitude: e.magnitude ?? 0,
      distanceKm: Math.round(haversineKm(city.lat, city.lon, e.latitude, e.longitude)),
    }))
    .filter((e) => e.distanceKm <= 2000)
    .sort((a, b) => b.magnitude - a.magnitude)
    .slice(0, 5);

  const tier = tierFrom(lambda5, maxMag);

  return {
    city: { name: city.name, country: city.country, popMillion: city.popMillion, lat: city.lat, lon: city.lon },
    computedAt: now.toISOString(),
    boundary,
    hasPlateContext: plateSet.size > 0,
    history: {
      years: 30,
      radiusKm: 400,
      totalM5: histEvents.length,
      lambda5: Math.round(lambda5 * 100) / 100,
      p1yM5: Math.round(poissonProb(lambda5) * 1000) / 10,
      lambda6: Math.round(lambda6 * 1000) / 1000,
      p1yM6: Math.round(poissonProb(lambda6) * 1000) / 10,
      maxMag: maxMag || null,
      maxEvent,
      byMag,
    },
    recentYear: {
      radiusKm: 300,
      count: recentEvents.length,
      top: recentEvents
        .sort((a, b) => (b.magnitude ?? 0) - (a.magnitude ?? 0))
        .slice(0, 5)
        .map((e) => ({ id: e.id, place: e.place, time: e.time, magnitude: e.magnitude })),
    },
    historyMap: histEvents
      .slice(0, 400)
      .map((e) => ({ lat: e.latitude, lon: e.longitude, mag: e.magnitude ?? 5 })),
    activeTriggers,
    tier,
    advice: ADVICE[tier.tier],
  };
}

export type ExposureResult = Awaited<ReturnType<typeof computeExposure>>;

export async function GET(req: NextRequest) {
  const city = req.nextUrl.searchParams.get("city");
  if (!city) return Response.json({ error: "Укажите параметр city" }, { status: 400 });

  try {
    await ensureSchema();
    const cached = await db.execute(sql`
      SELECT payload, EXTRACT(EPOCH FROM (now() - created_at)) * 1000 AS age_ms
      FROM exposure_cache WHERE city = ${city}
    `);
    const row = cached.rows[0];
    if (row && Number(row.age_ms) < CACHE_TTL) {
      return Response.json({ ok: true, cached: true, ...(row.payload as object) });
    }
  } catch {
    // fall through to computing without cache
  }

  try {
    const result = await computeExposure(city);
    if (!result) return Response.json({ error: "Город не найден в справочнике" }, { status: 404 });
    try {
      await ensureSchema();
      await db.execute(sql`
        INSERT INTO exposure_cache (city, payload, created_at)
        VALUES (${city}, ${JSON.stringify(result)}::jsonb, now())
        ON CONFLICT (city) DO UPDATE SET payload = EXCLUDED.payload, created_at = now()
      `);
    } catch {
      // cache write is best-effort
    }
    return Response.json({ ok: true, ...result });
  } catch {
    return Response.json({ error: "Не удалось рассчитать риск-профиль (USGS недоступен)" }, { status: 502 });
  }
}
