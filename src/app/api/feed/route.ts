import { fetchFeed } from "@/lib/usgs";
import { logSync } from "@/db/bootstrap";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

interface CacheEntry {
  data: unknown;
  at: number;
}
let cache: CacheEntry | null = null;
const TTL = 10 * 60 * 1000;

export async function GET() {
  if (cache && Date.now() - cache.at < TTL) {
    return Response.json({ ...(cache.data as object), cached: true });
  }
  try {
    const [significant, recent] = await Promise.all([
      fetchFeed("significant_month.geojson"),
      fetchFeed("4.5_week.geojson"),
    ]);
    const map = new Map<string, (typeof recent)[number]>();
    for (const e of [...recent, ...significant]) map.set(e.id, e);
    const events = [...map.values()]
      .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
      .slice(0, 30)
      .map((e) => ({
        id: e.id,
        magnitude: e.magnitude,
        magType: e.magType,
        place: e.place,
        time: e.time,
        latitude: e.latitude,
        longitude: e.longitude,
        depthKm: e.depthKm,
        tsunami: e.tsunami,
        alert: e.alert,
      }));
    const payload = { ok: true, events, updatedAt: new Date().toISOString() };
    cache = { data: payload, at: Date.now() };
    void logSync("usgs-feed", "ok", events.length);
    return Response.json(payload);
  } catch (e) {
    void logSync("usgs-feed", "error", undefined, e instanceof Error ? e.message : String(e));
    return Response.json(
      { ok: false, error: "Не удалось получить данные USGS (проверьте сетевое соединение)" },
      { status: 502 },
    );
  }
}
