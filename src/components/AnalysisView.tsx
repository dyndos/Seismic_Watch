"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  RefreshCw,
  Radio,
  Compass,
  Layers,
  Waves,
  MapPin,
  Building2,
  Info,
  ExternalLink,
  CircleCheck,
  CircleX,
  Timer,
} from "lucide-react";
import type { AnalysisResult } from "@/lib/types";
import { FAULT_TYPE_RU, FAULT_TYPE_DESCRIPTION_RU, contextualDirectionLabel } from "@/lib/classifier";
import {
  EXPLAIN_EXPECTED_COUNT,
  DISCLAIMER_AFTERSHOCK,
  DISCLAIMER_REGIONAL,
} from "@/lib/data";
import { fmtDateTimeUTC, fmtDateShort, fmtNum, fmtInt, fmtPct } from "@/lib/format";
import { Section, Stat, MagBadge, FaultBadge, Disclaimer, Bar, Skeleton, Nav } from "./ui";
import Map from "./Map";
import { Beachball } from "./Beachball";

const LOADING_STEPS = [
  "Запрашиваем событие и тензор момента из USGS…",
  "Строим индекс границ литосферных плит (PB2002)…",
  "Считаем историю региона за 20 лет…",
  "Прогнозируем афтершоки (Reasenberg–Jones)…",
  "Ищем исторические аналоги на плитной системе…",
  "Проводим hindcast-валидацию прогноза…",
];

export default function AnalysisView({ eventKey }: { eventKey: string }) {
  const [data, setData] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    const t = setInterval(() => setStep((s) => (s + 1) % LOADING_STEPS.length), 2200);
    return () => clearInterval(t);
  }, []);

  async function load(refresh = false) {
    setError(null);
    try {
      const resp = await fetch("/api/analyze", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ key: eventKey, refresh }),
      });
      const json = (await resp.json()) as AnalysisResult & { error?: string };
      if (!resp.ok) {
        setError(json.error ?? `Ошибка ${resp.status}`);
        return;
      }
      setData(json);
    } catch {
      setError("Сетевая ошибка при обращении к аналитическому модулю");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventKey]);

  if (error) {
    return (
      <div className="min-h-screen">
        <Nav />
        <div className="mx-auto max-w-2xl px-5 py-24 text-center">
          <div className="panel p-8">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-rose-500/15 ring-1 ring-rose-400/40">
              <CircleX className="h-6 w-6 text-rose-300" />
            </div>
            <h1 className="font-display text-xl font-semibold text-mist">Анализ не выполнен</h1>
            <p className="mt-2 text-sm text-fog">{error}</p>
            <div className="mt-6 flex justify-center gap-3">
              <button
                onClick={() => void load(true)}
                className="rounded-lg bg-signal/15 px-4 py-2 text-sm font-medium text-signal ring-1 ring-signal/40 transition hover:bg-signal/25"
              >
                Повторить
              </button>
              <Link href="/" className="rounded-lg px-4 py-2 text-sm text-fog ring-1 ring-line transition hover:text-mist">
                На дашборд
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen">
        <Nav />
        <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8">
          <div className="mb-8 flex items-center gap-4">
            <Skeleton className="h-16 w-28" />
            <div className="flex-1">
              <Skeleton className="h-6 w-2/3" />
              <Skeleton className="mt-2 h-4 w-1/3" />
            </div>
          </div>
          <Skeleton className="h-[520px] w-full" />
          <div className="mt-8 flex items-center justify-center gap-3 text-sm text-fog">
            <span className="h-2 w-2 animate-ping rounded-full bg-signal" />
            <span className="num">{LOADING_STEPS[step]}</span>
          </div>
          <p className="mt-2 text-center text-xs text-fog/60">
            Первый расчёт занимает 10–60 секунд (мировой каталог M≥6 за 20 лет). Повторные открытия — мгновенно из кэша.
          </p>
        </div>
      </div>
    );
  }

  return <AnalysisDashboard data={data} refreshing={refreshing} onRefresh={async () => {
    setRefreshing(true);
    await load(true);
    setRefreshing(false);
  }} />;
}

function AnalysisDashboard({
  data,
  refreshing,
  onRefresh,
}: {
  data: AnalysisResult;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const e = data.event;
  const nav = [
    ["map", "Карта"],
    ["focal", "Механизм"],
    ["aftershock", "Афтершоки"],
    ["history", "История"],
    ["regional", "Прогноз"],
    ["validation", "Валидация"],
    ["sequence", "Цепочка"],
    ["assets", "Объекты"],
  ] as const;

  return (
    <div className="min-h-screen">
      <Nav
        right={
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-fog ring-1 ring-line transition hover:text-mist disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            Обновить
          </button>
        }
      />

      {/* header */}
      <div className="border-b border-line-soft bg-abyss/40">
        <div className="mx-auto max-w-7xl px-5 py-7 sm:px-8">
          <Link href="/" className="mb-4 inline-flex items-center gap-1.5 text-sm text-fog transition hover:text-mist">
            <ArrowLeft className="h-4 w-4" /> К мониторингу
          </Link>
          <div className="flex flex-wrap items-start gap-5">
            <MagBadge mag={e.magnitude} size="lg" />
            <div className="min-w-0 flex-1">
              <h1 className="font-display text-2xl leading-tight font-bold text-mist sm:text-3xl">
                {data.isManual ? e.place : e.place.replace(/^(\d+km [NSWE]+ of )?/, "")}
              </h1>
              <div className="num mt-1.5 text-sm text-fog">{fmtDateTimeUTC(e.time)}</div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {data.focal ? <FaultBadge type={data.focal.faultType} /> : null}
                {data.isManual ? (
                  <span className="rounded-lg bg-violet-500/15 px-2.5 py-1 text-sm text-violet-300 ring-1 ring-violet-400/30">
                    Гипотетический сценарий
                  </span>
                ) : null}
                {e.tsunami ? (
                  <span className="inline-flex items-center gap-1 rounded-lg bg-sky-500/15 px-2.5 py-1 text-sm text-sky-300 ring-1 ring-sky-400/30">
                    <Waves className="h-3.5 w-3.5" /> Цунами-флаг USGS
                  </span>
                ) : null}
                {e.url ? (
                  <a
                    href={e.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-sm text-fog ring-1 ring-line transition hover:text-mist"
                  >
                    USGS <ExternalLink className="h-3 w-3" />
                  </a>
                ) : null}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-center sm:grid-cols-4">
              <MiniStat label="Глубина" value={`${fmtNum(e.depthKm, 0)} км`} />
              <MiniStat label="Широта" value={fmtNum(e.latitude, 2)} />
              <MiniStat label="Долгота" value={fmtNum(e.longitude, 2)} />
              <MiniStat label="Тип магнитуды" value={e.magType?.toUpperCase() ?? "—"} />
            </div>
          </div>
        </div>
      </div>

      {/* subnav */}
      <div className="sticky top-[57px] z-30 border-b border-line-soft/80 bg-ink/85 backdrop-blur-md">
        <div className="num mx-auto flex max-w-7xl gap-1 overflow-x-auto px-5 py-2 text-xs text-fog sm:px-8">
          {nav.map(([id, label]) => (
            <a key={id} href={`#${id}`} className="rounded-md px-3 py-1.5 whitespace-nowrap transition hover:bg-sky-400/10 hover:text-mist">
              {label}
            </a>
          ))}
        </div>
      </div>

      <div className="mx-auto max-w-7xl space-y-14 px-5 py-10 sm:px-8">
        {/* MAP */}
        <Section
          id="map"
          kicker="01 · Геовизуализация"
          title="Эпицентр, границы плит, афтершоки и цепочка событий"
          right={
            data.boundary ? (
              <div className="text-right text-sm text-fog">
                <div className="num">
                  граница {data.boundary.name} · {fmtInt(data.boundary.distanceKm)} км
                </div>
                <div className="text-signal">{data.boundary.plateNames.join(" ↔ ")}</div>
              </div>
            ) : undefined
          }
        >
          <Map
            center={[e.latitude, e.longitude]}
            zoom={data.isManual ? 5 : 5}
            epicenter={{ lat: e.latitude, lon: e.longitude, mag: e.magnitude, label: e.place }}
            slip={
              data.focal?.slipAzimuth != null
                ? {
                    lat: e.latitude,
                    lon: e.longitude,
                    azimuthDeg: data.focal.slipAzimuth,
                    lengthKm: Math.min(700, 90 + (e.magnitude ?? 6) * 55),
                  }
                : null
            }
            aftershocks={data.aftershocks30d}
            sequence={data.sequence}
            sites={data.nearbySites}
            cities={data.nearbyCities}
          />
          <div className="num mt-3 grid grid-cols-2 gap-2 text-xs text-fog sm:grid-cols-4">
            <div className="panel-inset px-3 py-2">Афтершоков M≥4 (30 дн): <span className="text-mist">{fmtInt(data.aftershocks30d.length)}</span></div>
            <div className="panel-inset px-3 py-2">Событий в цепочке (12 мес): <span className="text-mist">{data.sequence.length}</span></div>
            <div className="panel-inset px-3 py-2">Объектов в 1500 км: <span className="text-mist">{data.nearbySites.length}</span></div>
            <div className="panel-inset px-3 py-2">Городов в 1000 км: <span className="text-mist">{data.nearbyCities.length}</span></div>
          </div>
        </Section>

        {/* FOCAL MECHANISM */}
        <Section id="focal" kicker="02 · Тензор момента" title="Механизм очага и направление движения плиты">
          {data.focal ? (
            <div className="grid gap-5 lg:grid-cols-[auto_1fr]">
              <div className="panel flex flex-col items-center gap-2 p-5">
                <Beachball strike={data.focal.np1Strike} dip={data.focal.np1Dip} />
                <div className="text-center text-[11px] text-fog/70">
                  схематичная проекция, источник: {data.focal.tensorSource ?? "USGS"}
                </div>
              </div>
              <div className="space-y-4">
                <div className="panel p-5">
                  <div className="mb-2 flex items-center gap-2 text-lg font-semibold text-mist">
                    <Layers className="h-5 w-5 text-sky-300" />
                    {FAULT_TYPE_RU[data.focal.faultType]}
                  </div>
                  <p className="text-sm leading-relaxed text-fog">{FAULT_TYPE_DESCRIPTION_RU[data.focal.faultType]}</p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Stat
                    label="Азимут скольжения"
                    value={
                      <span className="num inline-flex items-center gap-2">
                        <Compass className="h-4 w-4 text-rose-400" />
                        {data.focal.slipAzimuth !== null ? `${fmtNum(data.focal.slipAzimuth)}°` : "—"}
                      </span>
                    }
                    hint={contextualDirectionLabel(data.focal.faultType)}
                  />
                  <Stat
                    label="Доля двойной пары"
                    value={<span className="num">{fmtPct((data.focal.pctDoubleCouple ?? 0) * 100)}</span>}
                    hint="близость источника к чистому сдвигу по разлому"
                  />
                </div>
                <div className="panel-inset overflow-x-auto p-4">
                  <table className="num w-full min-w-[420px] text-sm text-fog">
                    <thead>
                      <tr className="text-left text-xs text-fog/70 uppercase">
                        <th className="pb-2 pr-4">Нодальная плоскость</th>
                        <th className="pb-2 pr-4">Страйк (strike)</th>
                        <th className="pb-2 pr-4">Падение (dip)</th>
                        <th className="pb-2">Скольжение (rake)</th>
                      </tr>
                    </thead>
                    <tbody className="text-mist">
                      <tr>
                        <td className="py-1 pr-4 text-fog">NP1 (основная)</td>
                        <td className="py-1 pr-4">{fmtNum(data.focal.np1Strike)}°</td>
                        <td className="py-1 pr-4">{fmtNum(data.focal.np1Dip)}°</td>
                        <td className="py-1">{fmtNum(data.focal.np1Rake)}°</td>
                      </tr>
                      <tr>
                        <td className="py-1 pr-4 text-fog">NP2 (сопряжённая)</td>
                        <td className="py-1 pr-4">{fmtNum(data.focal.np2Strike)}°</td>
                        <td className="py-1 pr-4">{fmtNum(data.focal.np2Dip)}°</td>
                        <td className="py-1">{fmtNum(data.focal.np2Rake)}°</td>
                      </tr>
                    </tbody>
                  </table>
                  <p className="mt-3 flex items-start gap-2 text-xs leading-relaxed text-fog/80">
                    <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    По rake определяется тип разлома (0°/±180° — сдвиг, +90° — надвиг, −90° — сброс),
                    а по strike+dip — горизонтальная проекция движения поддвижной плиты. Тип разлома
                    показывает, КАК взаимодействуют плиты, азимут — В КАКУЮ сторону передаётся нагрузка.
                  </p>
                </div>
              </div>
            </div>
          ) : (
            <EmptyBox text="Для этого события USGS не опубликовал тензор момента — тип разлома и направление движения не определены. Межрегиональный анализ выполнен по базовым предположениям." />
          )}
        </Section>

        {/* AFTERSHOCKS */}
        {data.aftershock ? (
          <Section
            id="aftershock"
            kicker="03 · Reasenberg–Jones"
            title="Прогноз афтершоков"
            right={<span className="num text-sm text-fog">M{data.aftershock.mainMag.toFixed(1)} · a={data.aftershock.params.a} b={data.aftershock.params.b} p={data.aftershock.params.p}</span>}
          >
            <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
              <div className="panel overflow-x-auto p-5">
                <table className="num w-full min-w-[520px] text-sm">
                  <thead>
                    <tr className="text-left text-xs text-fog uppercase">
                      <th className="pb-3 pr-4">Период</th>
                      {["M3", "M4", "M5", "M6"].map((m) => (
                        <th key={m} className="pb-3 pr-4 text-center">
                          ≥ {m.replace("M", "M")}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.aftershock.windows.map((w) => (
                      <tr key={w.label} className="border-t border-line-soft">
                        <td className="py-3 pr-4 text-fog">{w.label}</td>
                        {["M3", "M4", "M5", "M6"].map((m) => {
                          const cell = w.cells[m];
                          if (!cell || cell.expected === null) {
                            return (
                              <td key={m} className="py-3 pr-4 text-center text-fog/40">—</td>
                            );
                          }
                          return (
                            <td key={m} className="py-3 pr-4 text-center">
                              <div className="text-mist">{fmtNum(cell.expected)}</div>
                              <div className="text-[11px] text-signal/80">P(≥1) = {fmtPct((cell.probability ?? 0) * 100)}</div>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="space-y-3">
                <div className="panel-inset p-4 text-sm leading-relaxed text-fog">
                  <div className="mb-1.5 flex items-center gap-1.5 font-semibold text-mist">
                    <Info className="h-4 w-4 text-signal" /> Как читать таблицу
                  </div>
                  {EXPLAIN_EXPECTED_COUNT}
                </div>
              </div>
            </div>
            <Disclaimer text={DISCLAIMER_AFTERSHOCK} />
          </Section>
        ) : (
          <Section id="aftershock" kicker="03 · Reasenberg–Jones" title="Прогноз афтершоков">
            <EmptyBox text="Событие слабее M5 — статистический прогноз афтершоков не строится." />
          </Section>
        )}

        {/* HISTORY */}
        <Section id="history" kicker="04 · База наблюдений" title="История региона: 20 лет, радиус 500 км">
          {data.history ? (
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="panel space-y-2.5 p-5">
                {data.history.bins.map((b, i) => (
                  <Bar
                    key={b.label}
                    label={b.label}
                    count={b.count}
                    max={Math.max(...data.history!.bins.map((x) => x.count))}
                    tone={i === 0 ? "bg-amber-400/70" : i === 1 ? "bg-orange-400/70" : i === 2 ? "bg-rose-400/70" : "bg-fuchsia-400/70"}
                  />
                ))}
                <div className="num pt-2 text-sm text-fog">
                  Всего M≥5: <span className="text-mist">{fmtInt(data.history.total)}</span> ·{" "}
                  {fmtNum(data.history.annualRate, 2)} событий/год · за последние 12 мес перед событием:{" "}
                  <span className="text-mist">{data.history.recent12m}</span>
                </div>
              </div>
              <div className="panel p-5">
                <div className="text-sm text-fog">Максимальное за период</div>
                {data.history.maxEvent ? (
                  <div className="mt-2 flex items-center gap-4">
                    <MagBadge mag={data.history.maxEvent.magnitude} />
                    <div>
                      <div className="text-sm text-mist">{data.history.maxEvent.place}</div>
                      <div className="num text-xs text-fog">{fmtDateShort(data.history.maxEvent.time)}</div>
                    </div>
                  </div>
                ) : (
                  <div className="mt-2 text-sm text-fog">нет данных</div>
                )}
                <p className="mt-4 text-xs leading-relaxed text-fog/80">
                  Длинный ряд наблюдений показывает «фоновую режимность» зоны: если регион за 20 лет не
                  давал M≥7, ожидать их следует реже — и наоборот. Это базовый уровень (baseline),
                  относительно которого интерпретируется триггерный сигнал.
                </p>
              </div>
            </div>
          ) : (
            <EmptyBox text="История региона недоступна (USGS не вернул данные)." />
          )}
        </Section>

        {/* REGIONAL FORECAST */}
        <Section id="regional" kicker="05 · Межрегиональная связка" title="Прогноз удалённой активности на той же плитной системе">
          {data.regional?.status === "ok" ? (
            <>
              <div className="mb-5 grid gap-3 sm:grid-cols-3">
                <Stat label="Плитная система" value={<span className="text-base">{data.regional.triggerPlateNames.join(" ↔ ")}</span>} hint="общая граница триггера и кандидатов" />
                <Stat label="Исторических аналогов" value={<span className="num">{data.regional.sampleSize}</span>} hint={`M≥${fmtNum(data.regional.triggerMinMag)} на этой системе за 20 лет`} />
                <Stat label="Условие «удалённости»" value={<span className="num">≥ {fmtInt(data.regional.minDistanceKm)} км</span>} hint={`M≥${fmtNum(data.regional.minRemoteMag)} и другой сегмент границы`} />
              </div>
              <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
                <div className="panel overflow-x-auto p-5">
                  <table className="num w-full min-w-[420px] text-sm">
                    <thead>
                      <tr className="text-left text-xs text-fog uppercase">
                        <th className="pb-3 pr-4">Горизонт</th>
                        <th className="pb-3 pr-4 text-center">Вероятность M≥{fmtNum(data.regional!.minRemoteMag)}</th>
                        <th className="pb-3 text-center">Историческая частота</th>
                      </tr>
                    </thead>
                    <tbody>
                      {["3m", "6m", "12m"].map((k) => {
                        const r = data.regional!.results[k];
                        if (!r) return null;
                        return (
                          <tr key={k} className="border-t border-line-soft">
                            <td className="py-3 pr-4 text-fog">{r.months} мес</td>
                            <td className="py-3 pr-4 text-center">
                              <ProbBar pct={r.percentage} />
                            </td>
                            <td className="py-3 text-center text-fog">
                              {r.triggered} из {r.total} триггеров
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="panel p-5">
                  <div className="mb-3 text-sm font-semibold text-mist">Активировавшиеся регионы (окно 6 мес, история)</div>
                  {data.regional.topRegions.length > 0 ? (
                    <div className="space-y-1.5">
                      {data.regional.topRegions.map((r) => (
                        <div key={r.region} className="flex items-center justify-between gap-3 text-sm">
                          <span className="truncate text-fog">{r.region}</span>
                          <span className="num shrink-0 text-signal">×{r.count}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-fog">нет данных</div>
                  )}
                </div>
              </div>
              <Disclaimer text={`${DISCLAIMER_REGIONAL} Каталог анализа: ${fmtInt(data.regional.catalogSize)} событий M≥6.`} />
            </>
          ) : (
            <EmptyBox text={data.regional?.message ?? "Событие слабее M6 или плитная система не определена — межрегиональный прогноз не строится."} />
          )}
        </Section>

        {/* VALIDATION */}
        <Section id="validation" kicker="06 · Hindcast" title="Проверка на истории: что говорила бы модель тогда и что случилось">
          {data.validation?.status === "ok" ? (
            <>
              <div className="grid gap-5 lg:grid-cols-3">
                {data.validation.horizons.map((h) => (
                  <div key={h.months} className="panel p-5">
                    <div className="flex items-center justify-between">
                      <div className="num text-sm text-fog">Горизонт {h.months} мес</div>
                      <Verdict observed={h.observed} coveragePct={h.coveragePct} />
                    </div>
                    <div className="mt-4 flex items-end gap-2">
                      <div className="num text-3xl font-bold text-mist">{fmtPct(h.predictedPct)}</div>
                      <div className="pb-1 text-xs text-fog">прогнозная вероятность<br />по {h.basedOn} аналогам прошлого</div>
                    </div>
                    {h.observed === "pending" ? (
                      <div className="num mt-3 text-xs text-amber-300/90">
                        горизонт ещё не закрыт ({h.coveragePct}% окна прошло)
                      </div>
                    ) : (
                      <div className="mt-3 space-y-1 text-xs text-fog">
                        {h.observedEvents.length > 0
                          ? h.observedEvents.map((ev) => (
                              <div key={ev.id} className="flex justify-between gap-2">
                                <span className="truncate">{ev.place}</span>
                                <span className="num shrink-0 text-emerald-300">M{ev.magnitude.toFixed(1)} · день {ev.daysAfter}</span>
                              </div>
                            ))
                          : <div>событий на системе не зафиксировано</div>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <p className="mt-4 text-sm leading-relaxed text-fog">{data.validation.summary}</p>
            </>
          ) : (
            <EmptyBox text={data.validation?.message ?? "Валидация недоступна для этого события."} />
          )}
        </Section>

        {/* SEQUENCE */}
        <Section id="sequence" kicker="07 · Фактическая цепочка" title="Значимые события в течение 12 месяцев после триггера">
          {data.sequence.length > 0 ? (
            <div className="panel overflow-x-auto p-5">
              <table className="num w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="text-left text-xs text-fog uppercase">
                    <th className="pb-3 pr-4">Дата</th>
                    <th className="pb-3 pr-4">M</th>
                    <th className="pb-3 pr-4">Регион</th>
                    <th className="pb-3 pr-4 text-right">Через, дн.</th>
                    <th className="pb-3 pr-4 text-right">Расстояние</th>
                    <th className="pb-3">Плитная система</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sequence.map((s) => (
                    <tr key={s.id} className="border-t border-line-soft">
                      <td className="py-2.5 pr-4 text-fog">{fmtDateShort(s.time)}</td>
                      <td className="py-2.5 pr-4"><MagBadge mag={s.magnitude} size="sm" /></td>
                      <td className="py-2.5 pr-4 text-mist">{s.region}</td>
                      <td className="py-2.5 pr-4 text-right text-fog">{s.daysAfter}</td>
                      <td className="py-2.5 pr-4 text-right text-fog">{fmtInt(s.distanceKm)} км</td>
                      <td className="py-2.5">
                        {s.sameSystem ? (
                          <span className="inline-flex items-center gap-1 text-emerald-300"><CircleCheck className="h-3.5 w-3.5" /> общая ({s.plates[0] ?? ""})</span>
                        ) : (
                          <span className="text-fog/70">иная</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-4 flex items-start gap-2 text-xs leading-relaxed text-fog/80">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                Модель взвешивает только события на общей плитной системе. События «иных» систем
                показаны для полноты картины (как в наблюдении «Турция → Марокко → Афганистан →
                Непал → Япония», 2023–24): попадание в список не означает причинной связи.
              </p>
            </div>
          ) : (
            <EmptyBox text="Заметных событий M≥6.2 в течение года после триггера не зафиксировано (или событие — гипотетический сценарий)." />
          )}
        </Section>

        {/* ASSETS */}
        <Section
          id="assets"
          kicker="08 · Бизнес-экспозиция"
          title="Объекты компании и крупные города"
          right={
            <Link href="/exposure" className="inline-flex items-center gap-1.5 rounded-lg bg-signal/10 px-3 py-1.5 text-xs font-medium text-signal ring-1 ring-signal/30 transition hover:bg-signal/20">
              <Building2 className="h-3.5 w-3.5" /> Оценить риск городов
            </Link>
          }
        >
          <div className="grid gap-5 lg:grid-cols-2">
            <div className="panel p-5">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-mist">
                <Building2 className="h-4 w-4 text-violet-300" /> Объекты в радиусе 1500 км
              </div>
              {data.nearbySites.length > 0 ? (
                <div className="space-y-2">
                  {data.nearbySites.map((s) => (
                    <div key={s.name} className="flex items-center justify-between gap-3 rounded-lg bg-abyss/60 px-3.5 py-2.5 ring-1 ring-line-soft">
                      <div>
                        <div className="text-sm text-mist">{s.name}</div>
                        <div className="text-xs text-fog/70">{s.siteType}</div>
                      </div>
                      <div className="num text-sm text-violet-300">{fmtInt(s.distanceKm)} км</div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyBox text="Объектов компании в радиусе 1500 км нет." small />
              )}
            </div>
            <div className="panel p-5">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-mist">
                <MapPin className="h-4 w-4 text-sky-300" /> Крупные города в радиусе 1000 км
              </div>
              {data.nearbyCities.length > 0 ? (
                <div className="space-y-2">
                  {data.nearbyCities.map((c) => (
                    <Link
                      key={c.name}
                      href={`/exposure?city=${encodeURIComponent(c.name)}`}
                      className="flex items-center justify-between gap-3 rounded-lg bg-abyss/60 px-3.5 py-2.5 ring-1 ring-line-soft transition hover:ring-sky-400/40"
                    >
                      <div>
                        <div className="text-sm text-mist">{c.name}, {c.country}</div>
                        <div className="text-xs text-fog/70">{fmtNum(c.popMillion)} млн жителей</div>
                      </div>
                      <div className="num text-sm text-sky-300">{fmtInt(c.distanceKm)} км</div>
                    </Link>
                  ))}
                </div>
              ) : (
                <EmptyBox text="Крупных городов справочника в радиусе 1000 км нет." small />
              )}
            </div>
          </div>
        </Section>

        <footer className="border-t border-line-soft pt-6 pb-4 text-xs leading-relaxed text-fog/70">
          Источники: каталог и тензоры момента USGS ComCat; границы плит PB2002 (Peter Bird, 2003).
          Модели: Reasenberg–Jones (1989) для афтершоков; эмпирические частоты последовательностей —
          для межрегиональных оценок. Инструмент аналитический, не является официальным прогнозом.
          Метка времени события: {e.time} (ISO 8601; дробная часть — миллисекунды, +00:00 — UTC).
        </footer>
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel-inset px-3 py-2">
      <div className="text-[10px] tracking-wide text-fog/80 uppercase">{label}</div>
      <div className="num mt-0.5 text-sm font-semibold text-mist">{value}</div>
    </div>
  );
}

function ProbBar({ pct }: { pct: number }) {
  const tone = pct >= 60 ? "text-rose-300" : pct >= 30 ? "text-amber-300" : "text-emerald-300";
  return (
    <div className="flex flex-col items-center gap-1">
      <span className={`num text-base font-bold ${tone}`}>{fmtPct(pct)}</span>
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-abyss ring-1 ring-line-soft">
        <div
          className={`h-full rounded-full ${pct >= 60 ? "bg-rose-400" : pct >= 30 ? "bg-amber-400" : "bg-emerald-400"}`}
          style={{ width: `${Math.min(100, Math.max(3, pct))}%` }}
        />
      </div>
    </div>
  );
}

function Verdict({ observed, coveragePct }: { observed: "yes" | "no" | "pending"; coveragePct: number }) {
  if (observed === "pending")
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/10 px-2 py-1 text-xs text-amber-300 ring-1 ring-amber-400/30">
        <Timer className="h-3 w-3" /> ожидание
      </span>
    );
  if (observed === "yes")
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/10 px-2 py-1 text-xs text-emerald-300 ring-1 ring-emerald-400/30">
        <CircleCheck className="h-3 w-3" /> подтверждено
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-slate-500/10 px-2 py-1 text-xs text-slate-300 ring-1 ring-slate-400/30">
      <CircleX className="h-3 w-3" /> не наступило
    </span>
  );
}

function EmptyBox({ text, small }: { text: string; small?: boolean }) {
  return (
    <div className={`flex items-center gap-3 rounded-xl border border-dashed border-line text-fog ${small ? "px-4 py-3 text-sm" : "px-5 py-6"}`}>
      <Radio className="h-4 w-4 shrink-0 text-fog/60" />
      <p className="leading-relaxed">{text}</p>
    </div>
  );
}
