import { Suspense } from "react";
import { Nav, Skeleton } from "@/components/ui";
import ExposureClient from "@/components/ExposureClient";

export const dynamic = "force-dynamic";

export default function ExposurePage() {
  return (
    <div className="min-h-screen">
      <Nav />
      <div className="mx-auto max-w-7xl px-5 py-10 sm:px-8">
        <div className="mb-2 text-[11px] tracking-[0.3em] text-signal/80 uppercase">Бизнес-тревел риск</div>
        <h1 className="font-display text-3xl font-bold text-mist sm:text-4xl">
          Сейсмический профиль городов
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-fog sm:text-base">
          Ожидаемая сейсмическая ситуация в регионе для планирования командировок: 30-летняя
          история каталога USGS в радиусе 400 км, частота и вероятность событий, ближайшая граница
          плит и активность последних 12 месяцев.
        </p>
        <Suspense fallback={<Skeleton className="mt-8 h-96 w-full" />}>
          <ExposureClient />
        </Suspense>
      </div>
    </div>
  );
}
