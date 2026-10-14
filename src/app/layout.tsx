import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Unbounded, Manrope, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const display = Unbounded({
  subsets: ["latin", "cyrillic"],
  variable: "--font-unbounded",
});

const body = Manrope({
  subsets: ["latin", "cyrillic"],
  variable: "--font-manrope",
});

const mono = JetBrains_Mono({
  subsets: ["latin", "cyrillic"],
  variable: "--font-jetbrains",
});

export const metadata: Metadata = {
  title: "Seismic Watch — аналитика межрегиональных триггерных цепочек",
  description:
    "Инструмент системного аналитика: оценка вероятного места и срока последующих землетрясений по типу разлома, статистике исторических последовательностей и границам литосферных плит (USGS, PB2002).",
  openGraph: {
    title: "Seismic Watch",
    description:
      "Оценка вероятного места и срока следующего землетрясения: тензор момента USGS, границы плит PB2002, статистика исторических последовательностей, hindcast-валидация.",
    images: ["/og.png"],
    type: "website",
    locale: "ru_RU",
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body className="min-h-screen antialiased">
        <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden />
        <div className="pointer-events-none fixed inset-0 bg-radial-fade" aria-hidden />
        <div className="relative">{children}</div>
      </body>
    </html>
  );
}
