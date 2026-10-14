"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Loader2,
  Newspaper,
  FlaskConical,
  Radio,
  Search,
} from "lucide-react";
import { fmtDateTimeUTC } from "@/lib/format";
import { MagBadge } from "./ui";
import type { FaultType } from "@/lib/types";

// ── Live significant events feed ───────────────────────────────────────────
interface FeedEvent {
  id: string;
  magnitude: number | null;
  place: string;
  time: string;
  depthKm: number | null;
  tsunami: boolean;
}

export function FeedLive() {
  const [events, setEvents] = useState<FeedEvent[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const router = useRouter();

  useEffect(() => {
    let alive = true;
    fetch("/api/feed")
      .then(async (r) => {
        const j = (await r.json()) as { events?: FeedEvent[]; error?: string };
        if (!alive) return;
        if (!r.ok) setErr(j.error ?? "Ошибка загрузки");
        else setEvents(j.events ?? []);
      })
      .catch(() => alive && setErr("USGS недоступен"));
    return () => {
      alive = false;
    };
  }, []);

  if (err) {
    return <div className="rounded-xl border border-dashed border-line px-4 py-6 text-sm text-fog">{err}</div>;
  }
  if (!events) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-14 animate-pulse rounded-xl bg-line-soft/40" />
        ))}
      </div>
    );
  }

  const shown = showAll ? events : events.slice(0, 8);
  return (
    <div className="space-y-2">
      {shown.map((e) => (
        <button
          key={e.id}
          onClick={() => router.push(`/analysis/${encodeURIComponent(e.id)}`)}
          className="group flex w-full items-center gap-3 rounded-xl bg-abyss/60 px-4 py-3 text-left ring-1 ring-line-soft transition hover:bg-panel2 hover:ring-sky-400/40"
        >
          <MagBadge mag={e.magnitude} size="sm" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm text-mist">{e.place}</div>
            <div className="num text-xs text-fog">{fmtDateTimeUTC(e.time)}</div>
          </div>
          <ArrowRight className="h-4 w-4 shrink-0 text-fog/40 transition group-hover:translate-x-0.5 group-hover:text-signal" />
        </button>
      ))}
      {events.length > 8 ? (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="num w-full rounded-lg py-2 text-center text-xs text-fog ring-1 ring-line transition hover:text-mist"
        >
          {showAll ? "Свернуть" : `Показать ещё ${events.length - 8}`}
        </button>
      ) : null}
    </div>
  );
}

// ── Hypothetical scenario form ─────────────────────────────────────────────
export function ManualScenarioForm() {
  const router = useRouter();
  const [form, setForm] = useState({
    latitude: "38.0",
    longitude: "38.0",
    magnitude: "7.0",
    depthKm: "10",
    place: "",
    faultType: "thrust" as FaultType,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const resp = await fetch("/api/analyze", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          spec: {
            latitude: Number(form.latitude),
            longitude: Number(form.longitude),
            magnitude: Number(form.magnitude),
            depthKm: Number(form.depthKm),
            place: form.place || undefined,
            faultType: form.faultType,
          },
        }),
      });
      const j = (await resp.json()) as { key?: string; error?: string };
      if (!resp.ok || !j.key) {
        setErr(j.error ?? "Не удалось выполнить расчёт");
        return;
      }
      router.push(`/analysis/${encodeURIComponent(j.key)}`);
    } catch {
      setErr("Сетевая ошибка");
    } finally {
      setBusy(false);
    }
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-2.5">
        <Field label="Широта" value={form.latitude} onChange={set("latitude")} type="number" step="0.01" />
        <Field label="Долгота" value={form.longitude} onChange={set("longitude")} type="number" step="0.01" />
        <Field label="Магнитуда" value={form.magnitude} onChange={set("magnitude")} type="number" step="0.1" />
        <Field label="Глубина, км" value={form.depthKm} onChange={set("depthKm")} type="number" step="1" />
      </div>
      <label className="block">
        <span className="mb-1 block text-xs text-fog">Предполагаемый тип разлома</span>
        <select
          value={form.faultType}
          onChange={(e) => setForm((f) => ({ ...f, faultType: e.target.value as FaultType }))}
          className="w-full rounded-lg bg-abyss px-3 py-2 text-sm text-mist ring-1 ring-line outline-none focus:ring-signal/50"
        >
          <option value="thrust">Надвиг (плиты сходятся)</option>
          <option value="normal">Сброс (плиты расходятся)</option>
          <option value="strike_slip">Сдвиг (скольжение)</option>
          <option value="oblique">Косое скольжение</option>
          <option value="unknown">Не знаю / без механизма</option>
        </select>
      </label>
      <Field label="Название места (необязательно)" value={form.place} onChange={set("place")} />
      {err ? <div className="text-sm text-rose-300">{err}</div> : null}
      <button
        type="submit"
        disabled={busy}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-violet-500/15 px-4 py-2.5 text-sm font-semibold text-violet-300 ring-1 ring-violet-400/40 transition hover:bg-violet-500/25 disabled:opacity-60"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
        {busy ? "Считаем (до 60 сек)…" : "Рассчитать сценарий"}
      </button>
    </form>
  );
}

// ── News / reference matching ──────────────────────────────────────────────
interface Candidate {
  id: string;
  place: string;
  time: string;
  magnitude: number | null;
  dtHours: number;
  distKm: number | null;
  score: number;
}

export function NewsMatchForm() {
  const router = useRouter();
  const [form, setForm] = useState({ magnitude: "", date: "", latitude: "", longitude: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [cands, setCands] = useState<Candidate[] | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setCands(null);
    try {
      const resp = await fetch("/api/match", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          magnitude: form.magnitude || undefined,
          date: form.date || undefined,
          latitude: form.latitude || undefined,
          longitude: form.longitude || undefined,
        }),
      });
      const j = (await resp.json()) as { candidates?: Candidate[]; error?: string };
      if (!resp.ok) {
        setErr(j.error ?? "Ошибка поиска");
        return;
      }
      setCands(j.candidates ?? []);
    } catch {
      setErr("Сетевая ошибка");
    } finally {
      setBusy(false);
    }
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="space-y-3">
      <form onSubmit={submit} className="space-y-3">
        <div className="grid grid-cols-2 gap-2.5">
          <Field label="Магнитуда из сводки" value={form.magnitude} onChange={set("magnitude")} type="number" step="0.1" placeholder="6.8" />
          <label className="block">
            <span className="mb-1 block text-xs text-fog">Дата события</span>
            <input
              type="date"
              value={form.date}
              onChange={set("date")}
              className="num w-full rounded-lg bg-abyss px-3 py-2 text-sm text-mist ring-1 ring-line outline-none focus:ring-signal/50"
            />
          </label>
          <Field label="Широта (если известна)" value={form.latitude} onChange={set("latitude")} type="number" step="0.01" />
          <Field label="Долгота (если известна)" value={form.longitude} onChange={set("longitude")} type="number" step="0.01" />
        </div>
        {err ? <div className="text-sm text-rose-300">{err}</div> : null}
        <button
          type="submit"
          disabled={busy}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-sky-500/15 px-4 py-2.5 text-sm font-semibold text-sky-300 ring-1 ring-sky-400/40 transition hover:bg-sky-500/25 disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          Найти в каталоге USGS
        </button>
      </form>
      {cands !== null ? (
        cands.length === 0 ? (
          <div className="flex items-center gap-2 rounded-lg border border-dashed border-line px-3 py-3 text-sm text-fog">
            <Radio className="h-4 w-4" /> Совпадений за ±48 часов не найдено
          </div>
        ) : (
          <div className="space-y-2">
            {cands.map((c) => (
              <button
                key={c.id}
                onClick={() => router.push(`/analysis/${encodeURIComponent(c.id)}`)}
                className="group flex w-full items-center gap-3 rounded-xl bg-abyss/60 px-3.5 py-2.5 text-left ring-1 ring-line-soft transition hover:ring-signal/40"
              >
                <MagBadge mag={c.magnitude} size="sm" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-mist">{c.place}</div>
                  <div className="num text-xs text-fog">
                    Δt {c.dtHours} ч{c.distKm !== null ? ` · Δs ${c.distKm} км` : ""} · score {c.score}
                  </div>
                </div>
                <Newspaper className="h-4 w-4 shrink-0 text-fog/40 group-hover:text-signal" />
              </button>
            ))}
          </div>
        )
      ) : null}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  step,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  type?: string;
  step?: string;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-fog">{label}</span>
      <input
        type={type}
        step={step}
        value={value}
        placeholder={placeholder}
        onChange={onChange}
        className="num w-full rounded-lg bg-abyss px-3 py-2 text-sm text-mist ring-1 ring-line outline-none placeholder:text-fog/40 focus:ring-signal/50"
      />
    </label>
  );
}
