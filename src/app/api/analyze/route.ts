import type { NextRequest } from "next/server";
import { runAnalysis, manualKey, MODEL_VERSION } from "@/lib/analysis";
import { getCachedAnalysis, saveAnalysis, logSync } from "@/db/bootstrap";
import type { ManualSpec } from "@/lib/types";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

function validateSpec(raw: unknown): ManualSpec | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const latitude = Number(r.latitude);
  const longitude = Number(r.longitude);
  const magnitude = Number(r.magnitude);
  if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90) return null;
  if (!Number.isFinite(longitude) || longitude < -180 || longitude > 180) return null;
  if (!Number.isFinite(magnitude) || magnitude < 3 || magnitude > 9.5) return null;
  const faultType =
    typeof r.faultType === "string" &&
    ["strike_slip", "thrust", "normal", "oblique"].includes(r.faultType)
      ? (r.faultType as ManualSpec["faultType"])
      : undefined;
  return {
    latitude,
    longitude,
    magnitude,
    depthKm: Number.isFinite(Number(r.depthKm)) ? Number(r.depthKm) : 10,
    place: typeof r.place === "string" ? r.place.slice(0, 160) : undefined,
    faultType,
  };
}

export async function POST(req: NextRequest) {
  let body: { key?: string; spec?: unknown; refresh?: boolean };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return Response.json({ error: "Некорректное тело запроса" }, { status: 400 });
  }

  const spec = validateSpec(body.spec);
  let key = typeof body.key === "string" ? body.key : undefined;
  if (!key && spec) key = manualKey(spec);
  if (!key) return Response.json({ error: "Укажите key события или spec сценария" }, { status: 400 });

  if (!body.refresh) {
    const cached = await getCachedAnalysis(key);
    if (cached && cached.modelVersion === MODEL_VERSION) return Response.json(cached);
  }

  try {
    const result = await runAnalysis(key, spec ?? undefined);
    await saveAnalysis(key, result);
    void logSync("usgs-analysis", "ok");
    return Response.json(result);
  } catch (e) {
    const err = e as { status?: number; message?: string };
    const status = err.status ?? 502;
    void logSync("usgs-analysis", "error", undefined, err.message);
    return Response.json(
      { error: err.message ?? "Ошибка анализа (возможно, недоступен USGS)" },
      { status },
    );
  }
}
