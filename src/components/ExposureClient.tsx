"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Building2,
  MapPin,
  Loader2,
  AlertTriangle,
  ShieldCheck,
  Plane,
  History,
  Radio,
} from "lucide-react";
import { MAJOR_CITIES } from "@/lib/data";
import { fmtDateShort, fmtNum, fmtInt, fmtPct } from "@/lib/format";
import { Bar, MagBadge, Stat } from "./ui";
import Map from "./Map";

interface ExposureData {
  ok: boolean;
  city: { name: string; country: string; popMillion: number; lat: number; lon: number };
  computedAt: string;
  boundary: { distanceKm: number; name: string; plateNames: string[]; boundaryType: string | null } | null;
  history: {
    years: number;
    radiusKm: number;
    totalM5: number;
    lambda5: number;
    p1yM5: number;
    p1yM6: number;
    maxMag: number | null;
    maxEvent: { id: string; place: string; time: string; magnitude: number } | null;
    byMag: { label: string; count: number }[];
  };
  recentYear: {
    radiusKm: number;
    count: number;
    top: { id: string; place: string; time: string; magnitude: number | null }[];
  };
  historyMap: { lat: number; lon: number; mag: number }[];
  activeTriggers: {
    id: string;
    region: string;
    time: string;
    magnitude: number;
    distanceKm: number;
  }[];
  tier: { tier: number; label: string; color: string };
  advice: string[];
}

const TONE: Record<string, { ring: string; bg: string; text: string }> = {
  rose: { ring: "ring-rose-400/50", bg: "bg-rose-500/10", text: "text-rose-300" },
  orange: { ring: "ring-orange-400/50", bg: "bg-orange-500/10", text: "text-orange-300" },
  amber: { ring: "ring-amber-400/50", bg: "bg-amber-500/10", text: "text-amber-300" },
  emerald: { ring: "ring-emerald-400/50", bg: "bg-emerald-500/10", text: "text-emerald-300" },
};

export default function ExposureClient() {
  const params = useSearchParams();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string>(params.get("city") ?? "Стамбул");
  const [data, setData] = useState<ExposureData | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const cities = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? MAJOR_CITIES.filter(
          (c) => c.name.toLowerCase().includes(q) || c.country.toLowerCase() === q,
        )
      : MAJOR_CITIES;
    return [...list].sort((a, b) => a.name.localeCompare(b.name, "ru"));
  }, [query]);

  useEffect(() => {
    if (!selected) return;
    let alive = true;
    setBusy(true);
    setErr(null);
    fetch(`/api/exposure?city=${encodeURIComponent(selected)}`)
      .then(async (r) => {
        const j = (await r.json()) as ExposureData & { error?: string };
        if (!alive) return;
        if (!r.ok) setErr(j.error ?? "Ошибка расчёта");
        else setData(j);
      })
      .catch(() => alive && setErr("Сетевая ошибка"))
      .finally(() => alive && setBusy(false));
    return () => {
      alive = false;
    };
  }, [selected]);

  const tone = data ? TONE[data.tier.color] ?? TONE.amber : TONE.amber;

  return (
    <div className="mt-8 grid gap-5 lg:grid-cols-[300px_1fr]">
      {/* city picker */}
      <div className="panel h-fit p-4 lg:sticky lg:top-24">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Поиск города…"
          className="num mb-3 w-full rounded-lg bg-abyss px-3 py-2 text-sm text-mist ring-1 ring-line outline-none placeholder:text-fog/40 focus:ring-signal/50"
        />
        <div className="max-h-[420px] space-y-1 overflow-y-auto pr-1">
          {cities.map((c) => (
            <button
              key={c.name}
              onClick={() => setSelected(c.name)}
              className={`flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm transition ${
                selected === c.name
                  ? "bg-signal/15 text-signal ring-1 ring-signal/40"
                  : "text-fog hover:bg-sky-400/10 hover:text-mist"
              }`}
            >
              <span className="truncate">{c.name}</span>
              <span className="num shrink-0 text-xs opacity-60">{c.country}</span>
            </button>
          ))}
        </div>
      </div>

      {/* briefing */}
      <div className="min-w-0">
        {busy && !data ? (
          <div className="flex h-64 items-center justify-center gap-2 text-fog">
            <Loader2 className="h-5 w-5 animate-spin" /> Считаем 30-летний профиль…
          </div>
        ) : err ? (
          <div className="flex items-center gap-3 rounded-xl border border-dashed border-line px-5 py-6 text-fog">
            <AlertTriangle className="h-4 w-4 text-warn" /> {err}
          </div>
        ) : data ? (
          <div className={`animate-fade-up space-y-5 ${busy ? "opacity-60 transition" : ""}`}>
            {/* tier banner */}
            <div className={`panel ${tone.ring} ${tone.bg} flex flex-wrap items-center justify-between gap-4 p-5 ring-1`}>
              <div>
                <div className="flex items-center gap-2.5">
                  <MapPin className={`h-5 w-5 ${tone.text}`} />
                  <h2 className="font-display text-xl font-bold text-mist sm:text-2xl">
                    {data.city.name}
                    <span className="num ml-2 text-sm font-medium text-fog">{data.city.country} · {fmtNum(data.city.popMillion)} млн</span>
                  </h2>
                </div>
                <div className={`mt-1.5 text-sm font-semibold ${tone.text}`}>{data.tier.label}</div>
              </div>
              <div className="num text-right text-xs text-fog">
                <div>обновлено {fmtDateShort(data.computedAt)}</div>
                {data.boundary ? (
                  <div className="mt-1">
                    граница {data.boundary.name} · {fmtInt(data.boundary.distanceKm)} км
                    <div className="text-signal">{data.boundary.plateNames.join(" ↔ ")}</div>
                  </div>
                ) : null}
              </div>
            </div>

            {/* key numbers */}
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Stat
                label="P(≥1 события M5+) за год"
                value={<span className={`num ${tone.text}`}>{fmtPct(data.history.p1yM5, 1)}</span>}
                hint={`по Poisson, λ = ${fmtNum(data.history.lambda5, 2)}/год`}
              />
              <Stat
                label="P(≥1 события M6+) за год"
                value={<span className="num text-mist">{fmtPct(data.history.p1yM6, 1)}</span>}
                hint="в радиусе 400 км"
              />
              <Stat
                label="Событий M5+ за 30 лет"
                value={<span className="num text-mist">{fmtInt(data.history.totalM5)}</span>}
                hint="каталог USGS, радиус 400 км"
              />
              <Stat
                label="Активность за 12 мес"
                value={<span className="num text-mist">{fmtInt(data.recentYear.count)}</span>}
                hint="M≥4 в радиусе 300 км"
              />
            </div>

            {/* map */}
            <Map
              center={[data.city.lat, data.city.lon]}
              zoom={4}
              epicenter={{ lat: data.city.lat, lon: data.city.lon, mag: null, label: `${data.city.name} — центр оценки` }}
              extraEvents={data.historyMap}
              ringsKm={[200, 400]}
            />
            <div className="num -mt-2 text-xs text-fog/70">точки — события M≥5 за 30 лет; кольца — 200 и 400 км</div>

            <div className="grid gap-5 lg:grid-cols-2">
              {/* distribution + max */}
              <div className="panel p-5">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-mist">
                  <History className="h-4 w-4 text-sky-300" /> Распределение по магнитудам
                </div>
                <div className="space-y-2.5">
                  {data.history.byMag.map((b, i) => (
                    <Bar
                      key={b.label}
                      label={b.label}
                      count={b.count}
                      max={Math.max(1, ...data.history.byMag.map((x) => x.count))}
                      tone={i === 0 ? "bg-amber-400/70" : i === 1 ? "bg-orange-400/70" : "bg-rose-400/70"}
                    />
                  ))}
                </div>
                {data.history.maxEvent ? (
                  <div className="mt-4 flex items-center gap-3 rounded-lg bg-abyss/60 px-3.5 py-3 ring-1 ring-line-soft">
                    <MagBadge mag={data.history.maxEvent.magnitude} size="sm" />
                    <div className="min-w-0">
                      <div className="truncate text-sm text-mist">Максимум за 30 лет: {data.history.maxEvent.place}</div>
                      <div className="num text-xs text-fog">{fmtDateShort(data.history.maxEvent.time)}</div>
                    </div>
                  </div>
                ) : null}
              </div>

              {/* recent + triggers */}
              <div className="panel p-5">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-mist">
                  <Radio className="h-4 w-4 text-signal" /> Фон последних 12 месяцев
                </div>
                {data.recentYear.top.length > 0 ? (
                  <div className="space-y-1.5">
                    {data.recentYear.top.map((e) => (
                      <div key={e.id} className="flex items-center justify-between gap-3 text-sm">
                        <span className="truncate text-fog">{e.place}</span>
                        <span className="num shrink-0 text-mist">M{e.magnitude?.toFixed(1)} · {fmtDateShort(e.time)}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-fog">Событий M≥4 в радиусе 300 км не было.</div>
                )}
                {data.activeTriggers.length > 0 ? (
                  <>
                    <div className="mt-4 border-t border-line-soft pt-3 text-xs font-semibold text-fog uppercase">
                      Крупные M≥6.5 в пределах 2000 км за год
                    </div>
                    <div className="mt-2 space-y-1.5">
                      {data.activeTriggers.map((t) => (
                        <a key={t.id} href={`/analysis/${t.id}`} className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm transition hover:bg-sky-400/10">
                          <span className="truncate text-fog">{t.region}</span>
                          <span className="num shrink-0 text-orange-300">M{t.magnitude.toFixed(1)} · {fmtInt(t.distanceKm)} км</span>
                        </a>
                      ))}
                    </div>
                  </>
                ) : null}
              </div>
            </div>

            {/* advice */}
            <div className="panel p-5">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-mist">
                <Plane className="h-4 w-4 text-violet-300" /> Рекомендации для командировок и размещения активов
              </div>
              <ul className="space-y-2">
                {data.advice.map((a) => (
                  <li key={a} className="flex items-start gap-2 text-sm leading-relaxed text-fog">
                    <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-signal" />
                    {a}
                  </li>
                ))}
              </ul>
              <p className="mt-4 text-xs leading-relaxed text-fog/70">
                Оценка — статистическая (каталог USGS, 30 лет, радиус 400 км; Poisson).
                Для решений о строительстве используйте официальные карты сейсмического
                районирования (например, ОСР/GSHAP).
              </p>
            </div>
          </div>
        ) : (
          <div className="flex h-64 items-center justify-center gap-2 text-fog">
            <Building2 className="h-5 w-5" /> Выберите город слева
          </div>
        )}
      </div>
    </div>
  );
}
