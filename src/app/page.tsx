import Link from "next/link";
import {
  Radio,
  Activity,
  FlaskConical,
  Newspaper,
  Building2,
  ChevronRight,
  Database,
  GitBranch,
  LineChart,
  MapPinned,
  Clock3,
  Sigma,
  History,
  Map,
  ShieldAlert,
} from "lucide-react";
import { Nav } from "@/components/ui";
import { FeedLive, ManualScenarioForm, NewsMatchForm } from "@/components/DashboardClient";
import { listRecentAnalyses } from "@/db/bootstrap";
import { NOTABLE_EVENTS, EXPLAIN_TIMESTAMP } from "@/lib/data";
import { fmtDateShort } from "@/lib/format";

export const dynamic = "force-dynamic";

const STEPS = [
  {
    icon: Database,
    title: "Данные наблюдений",
    text: "Каталог USGS ComCat (события и тензоры момента) и модель границ литосферных плит PB2002 — обе базы открыты в сети и обновляются.",
  },
  {
    icon: GitBranch,
    title: "Тип разлома",
    text: "По strike/dip/rake тензора момента классифицируем механизм: надвиг, сброс, сдвиг. Это отвечает на вопрос «как и куда движется плита».",
  },
  {
    icon: History,
    title: "Статистика последовательностей",
    text: "В каталоге за 20 лет ищем исторические аналоги на той же плитной системе и считаем, как часто за ними следовали удалённые события M≥6.",
  },
  {
    icon: LineChart,
    title: "Вероятности по горизонтам",
    text: "Формируем оценку для окон 3 / 6 / 12 месяцев без ограничения по расстоянию внутри системы плит — и проверяем её hindcast-валидацией.",
  },
];

const FAQ = [
  {
    q: "Есть ли историческое подтверждение спрогнозированным здесь событиям?",
    a: "Да — в карточке анализа есть раздел «Hindcast»: модель «отматывается» на дату триггера, вероятность считается только по данным, которые существовали до события, а затем сверяется с тем, что реально произошло за 3/6/12 месяцев. Для Турции-2023 через 214 дней последовал Марокко M6.8, через ~9 месяцев — Непал и Афганистанский кластер, через 10,5 месяцев — Ното (Япония). Одиночная проверка не доказывает качество модели — это демонстрация механизма валидации.",
  },
  {
    q: "Что значат числа вроде 913.7 при M≥3 в прогнозе афтершоков?",
    a: "Это математическое ожидание количества событий: «за указанный период модель в среднем ожидает ~914 событий магнитудой от 3». Это не вероятность. Поэтому рядом с каждым ожиданием мы показываем вероятность хотя бы одного события по пуассоновской модели P(≥1) = 1 − e^(−N): для 913.7 она ≈100%, для 0.9 — ≈59%.",
  },
  {
    q: "Что означает «.342000+00:00» в метках времени? Это нужно?",
    a: EXPLAIN_TIMESTAMP,
  },
  {
    q: "Рисуется ли это на карте?",
    a: "Да. Интерактивная карта показывает эпицентр, афтершоки за 30 дней, границы плит PB2002, стрелку направления движения плиты, кольца радиусов 500/1000/1500 км, объекты компании, крупные города и всю фактическую цепочку последующих событий с флагом «та же плитная система».",
  },
  {
    q: "Почему расстояние не ограничено? Как Турция связана с Марокко?",
    a: "Перенос напряжений после крупных событий действует не по кругу вокруг эпицентра, а вдоль тектонических структур: Альпийско-Гималайский пояс связывает Анатолийскую, Африканскую и Аравийскую плиты. Модель поэтому проверяет события на ВСЕЙ системе плит триггера, но честно помечает события иных систем как «иная» — корреляция не равна причинности.",
  },
];

export default async function DashboardPage() {
  const recent = await listRecentAnalyses(6);

  return (
    <div className="min-h-screen">
      <Nav />

      {/* HERO */}
      <div className="relative overflow-hidden border-b border-line-soft">
        <div className="mx-auto max-w-7xl px-5 pt-16 pb-14 sm:px-8 sm:pt-24">
          <div className="animate-fade-up">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full bg-signal/10 px-3.5 py-1.5 text-xs font-medium text-signal ring-1 ring-signal/30">
              <span className="animate-pulse-soft h-1.5 w-1.5 rounded-full bg-signal" />
              Живые данные USGS · границы плит PB2002
            </div>
            <h1 className="font-display max-w-4xl text-4xl leading-[1.05] font-bold text-mist sm:text-6xl">
              Куда передаст нагрузку{" "}
              <span className="glow-text text-signal">следующее землетрясение</span>?
            </h1>
            <p className="mt-6 max-w-2xl text-base leading-relaxed text-fog sm:text-lg">
              По типу разлома (надвиг, сброс или сдвиг) определяем направление движения плиты и по
              статистике исторических последовательностей оцениваем, где на той же плитной системе
              в течение 3–12 месяцев вероятно следующее значимое событие. Включая цепочки в других
              регионах — как Турция 2023 → Марокко → Афганистан → Непал → Япония.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <a
                href="#monitor"
                className="inline-flex items-center gap-2 rounded-xl bg-signal px-5 py-3 text-sm font-bold text-ink transition hover:brightness-110"
              >
                <Activity className="h-4 w-4" /> Открыть мониторинг
              </a>
              <Link
                href={`/analysis/${NOTABLE_EVENTS[0].id}`}
                className="inline-flex items-center gap-2 rounded-xl px-5 py-3 text-sm font-semibold text-mist ring-1 ring-line transition hover:bg-sky-400/10"
              >
                Разбор Турции 2023 <ChevronRight className="h-4 w-4" />
              </Link>
              <Link
                href="/exposure"
                className="inline-flex items-center gap-2 rounded-xl px-5 py-3 text-sm font-semibold text-mist ring-1 ring-line transition hover:bg-sky-400/10"
              >
                <Building2 className="h-4 w-4" /> Риск городов и командировок
              </Link>
            </div>
          </div>
        </div>
        <div className="num pointer-events-none absolute -right-6 bottom-2 hidden select-none text-[120px] leading-none font-bold text-line-soft/60 lg:block">
          37.15°N
        </div>
      </div>

      {/* MONITOR */}
      <div id="monitor" className="mx-auto max-w-7xl scroll-mt-20 px-5 py-12 sm:px-8">
        <div className="mb-6 flex items-center gap-3">
          <Radio className="h-5 w-5 text-signal" />
          <h2 className="font-display text-2xl font-bold text-mist">Мониторинг событий</h2>
        </div>

        <div className="grid gap-5 lg:grid-cols-3">
          {/* feed */}
          <div className="panel p-5 lg:row-span-2">
            <div className="mb-4 flex items-center justify-between">
              <div className="text-sm font-semibold text-mist">Значимые события (USGS, 30 дней)</div>
              <span className="num rounded-md bg-line-soft/60 px-2 py-0.5 text-[10px] text-fog">live</span>
            </div>
            <FeedLive />
          </div>

          {/* presets */}
          <div className="panel p-5">
            <div className="mb-4 text-sm font-semibold text-mist">Кейсы для разбора</div>
            <div className="space-y-2">
              {NOTABLE_EVENTS.map((e) => (
                <Link
                  key={e.id}
                  href={`/analysis/${e.id}`}
                  className="group flex items-center gap-3 rounded-xl bg-abyss/60 px-4 py-3 ring-1 ring-line-soft transition hover:bg-panel2 hover:ring-rose-400/40"
                >
                  <span className="num shrink-0 rounded-lg bg-rose-500/15 px-2 py-0.5 text-sm font-bold text-rose-300 ring-1 ring-rose-400/40">
                    M{e.mag.toFixed(1)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm text-mist">{e.label}</div>
                    <div className="num text-xs text-fog">{e.date}</div>
                  </div>
                  <ChevronRight className="h-4 w-4 shrink-0 text-fog/40 transition group-hover:translate-x-0.5 group-hover:text-rose-300" />
                </Link>
              ))}
            </div>
            {recent.length > 0 ? (
              <div className="mt-5 border-t border-line-soft pt-4">
                <div className="mb-2 flex items-center gap-1.5 text-xs text-fog">
                  <Clock3 className="h-3.5 w-3.5" /> Недавно рассчитанные
                </div>
                <div className="space-y-1.5">
                  {recent.map((r) => (
                    <Link
                      key={r.key}
                      href={`/analysis/${encodeURIComponent(r.key)}`}
                      className="flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-sm text-fog transition hover:bg-sky-400/10 hover:text-mist"
                    >
                      <span className="truncate">{r.place}</span>
                      <span className="num shrink-0 text-xs">{r.mag !== null ? `M${r.mag.toFixed(1)}` : ""} {fmtDateShort(r.time)}</span>
                    </Link>
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          {/* manual scenario */}
          <div className="panel p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-mist">
              <FlaskConical className="h-4 w-4 text-violet-300" /> Гипотетический сценарий
            </div>
            <p className="mb-3 text-xs leading-relaxed text-fog">
              «Что если M7.5 произойдёт в точке X?» — ввод места и магнитуды из справочников для
              оценки последствий.
            </p>
            <ManualScenarioForm />
          </div>

          {/* news matching */}
          <div className="panel p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-mist">
              <Newspaper className="h-4 w-4 text-sky-300" /> Сопоставление новости с каталогом
            </div>
            <p className="mb-3 text-xs leading-relaxed text-fog">
              Из новостной сводки известны магнитуда и дата — находим событие в каталоге USGS по
              окну ±48 часов и близости параметров.
            </p>
            <NewsMatchForm />
          </div>
        </div>
      </div>

      {/* METHODOLOGY */}
      <div className="border-t border-line-soft bg-abyss/30">
        <div className="mx-auto max-w-7xl px-5 py-14 sm:px-8">
          <div className="mb-8">
            <div className="num text-[11px] tracking-[0.3em] text-signal/80 uppercase">Методология</div>
            <h2 className="font-display mt-2 text-2xl font-bold text-mist sm:text-3xl">Как работает оценка</h2>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <div key={s.title} className="panel group p-5 transition hover:ring-1 hover:ring-signal/30">
                <div className="mb-3 flex items-center justify-between">
                  <s.icon className="h-5 w-5 text-signal" />
                  <span className="num text-xs text-fog/50">0{i + 1}</span>
                </div>
                <div className="font-display text-sm font-semibold text-mist">{s.title}</div>
                <p className="mt-2 text-xs leading-relaxed text-fog">{s.text}</p>
              </div>
            ))}
          </div>

          <div className="mt-10 grid gap-4 lg:grid-cols-[1fr_1fr]">
            <div className="panel p-6">
              <div className="mb-4 flex items-center gap-2 font-semibold text-mist">
                <Map className="h-5 w-5 text-sky-300" /> Что есть в карточке анализа
              </div>
              <ul className="grid gap-2.5 text-sm text-fog sm:grid-cols-2">
                {[
                  "Карта: эпицентр, границы плит, кольца 500/1000/1500 км",
                  "Стрелка направления движения плиты по типу разлома",
                  "Механизм очага: nodal planes, beachball-схема",
                  "Прогноз афтершоков: ожидание + вероятность P(≥1)",
                  "Межрегиональный прогноз 3/6/12 мес по системе плит",
                  "Hindcast-валидация против реальной цепочки событий",
                  "Фактическая последовательность за 12 месяцев",
                  "Объекты компании и крупные города в зоне влияния",
                ].map((t) => (
                  <li key={t} className="flex items-start gap-2">
                    <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal" />
                    {t}
                  </li>
                ))}
              </ul>
            </div>
            <div className="panel p-6">
              <div className="mb-4 flex items-center gap-2 font-semibold text-mist">
                <ShieldAlert className="h-5 w-5 text-warn" /> Границы применимости
              </div>
              <ul className="space-y-2.5 text-sm leading-relaxed text-fog">
                <li className="flex items-start gap-2">
                  <Sigma className="mt-1 h-3.5 w-3.5 shrink-0 text-warn" />
                  Вероятности — эмпирические частоты, а не физическая модель передачи напряжений
                  Кулона (для неё нужна 3D-геометрия разломов).
                </li>
                <li className="flex items-start gap-2">
                  <Sigma className="mt-1 h-3.5 w-3.5 shrink-0 text-warn" />
                  Корреляция событий на общей плитной системе не доказывает причинной связи —
                  это гипотеза, обёрнутая в измеримый процесс.
                </li>
                <li className="flex items-start gap-2">
                  <Sigma className="mt-1 h-3.5 w-3.5 shrink-0 text-warn" />
                  Инструмент не является официальным прогнозом и не заменяет решения служб
                  гражданской защиты.
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      {/* FAQ */}
      <div className="mx-auto max-w-7xl px-5 py-14 sm:px-8">
        <div className="mb-6">
          <div className="num text-[11px] tracking-[0.3em] text-signal/80 uppercase">Вопросы по механике</div>
          <h2 className="font-display mt-2 text-2xl font-bold text-mist sm:text-3xl">Разбор частых вопросов</h2>
        </div>
        <div className="space-y-3">
          {FAQ.map((f) => (
            <details key={f.q} className="group panel overflow-hidden">
              <summary className="flex cursor-pointer items-center justify-between gap-4 px-5 py-4 text-sm font-semibold text-mist transition hover:text-signal sm:text-base [&::-webkit-details-marker]:hidden">
                {f.q}
                <ChevronRight className="h-4 w-4 shrink-0 text-fog transition duration-300 group-open:rotate-90 group-open:text-signal" />
              </summary>
              <div className="border-t border-line-soft px-5 py-4 text-sm leading-relaxed text-fog">
                {f.a}
              </div>
            </details>
          ))}
        </div>

        <footer className="mt-12 flex flex-wrap items-center justify-between gap-3 border-t border-line-soft pt-6 pb-4 text-xs text-fog/70">
          <span className="inline-flex items-center gap-2">
            <MapPinned className="h-3.5 w-3.5" />
            Seismic Watch · портфолио системного аналитика · данные: USGS, PB2002 (Peter Bird, 2003)
          </span>
          <span className="num">model: RJ-89 · plate-chain stats v1</span>
        </footer>
      </div>
    </div>
  );
}
