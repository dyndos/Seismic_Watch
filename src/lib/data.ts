/**
 * Reference datasets (client & server safe, no I/O).
 */

// ── Tectonic plate codes (PB2002 model) ────────────────────────────────────
export const PLATE_NAMES: Record<string, string> = {
  AF: "Африканская", AN: "Антарктическая", AR: "Аравийская",
  AU: "Австралийская", BU: "Бирманская", CA: "Карибская",
  CO: "Кокос", EU: "Евразийская", IN: "Индийская",
  JF: "Хуан-де-Фука", NA: "Северо-Американская", NZ: "Наска",
  OK: "Охотская", PA: "Тихоокеанская", PH: "Филиппинская",
  PS: "Филиппинская", SA: "Южно-Американская", SC: "Скотия",
  SU: "Зондская", YA: "Янцзы", AM: "Амурская",
  AP: "Альтиплано", AS: "Эгейская", AT: "Анатолийская",
  RI: "Ривера", PM: "Панамская", KE: "Кермадек", TO: "Тонга",
  NI: "Ниуафооу", NH: "Новые Гебриды", NB: "Сев. Бисмарка",
  SB: "Южн. Бисмарка", MN: "Манус", MO: "Маоке", BH: "Голова птицы",
  BS: "Банда", MS: "Молуккская", SS: "Соломонова", WL: "Вудларк",
  SL: "Шетландская", SW: "Сандвичева", SO: "Сомалийская", TI: "Тимор",
  CL: "Карат", BR: "Балморал", CR: "Конуэй", FT: "Футуна",
  MA: "Марианская", ON: "Окинавская", EA: "Пасхи", GP: "Галапагосская",
  ND: "Северо-Андская",
};

export function plateName(code: string): string {
  return PLATE_NAMES[code] ?? code;
}

// ── Major cities in seismically active regions (for exposure alerts) ───────
export interface CityRef {
  name: string;
  country: string;
  popMillion: number;
  lat: number;
  lon: number;
}

export const MAJOR_CITIES: CityRef[] = [
  { name: "Токио",         country: "JP", popMillion: 13.9, lat: 35.6762,  lon: 139.6503 },
  { name: "Осака",         country: "JP", popMillion: 2.7,  lat: 34.6937,  lon: 135.5023 },
  { name: "Стамбул",       country: "TR", popMillion: 15.6, lat: 41.0082,  lon: 28.9784 },
  { name: "Анкара",        country: "TR", popMillion: 5.7,  lat: 39.9334,  lon: 32.8597 },
  { name: "Газиантеп",     country: "TR", popMillion: 2.1,  lat: 37.0662,  lon: 37.3833 },
  { name: "Тегеран",       country: "IR", popMillion: 9.0,  lat: 35.6892,  lon: 51.3890 },
  { name: "Манила",        country: "PH", popMillion: 14.4, lat: 14.5995,  lon: 120.9842 },
  { name: "Мехико",        country: "MX", popMillion: 21.8, lat: 19.4326,  lon: -99.1332 },
  { name: "Сантьяго",      country: "CL", popMillion: 6.8,  lat: -33.4489, lon: -70.6693 },
  { name: "Лима",          country: "PE", popMillion: 10.7, lat: -12.0464, lon: -77.0428 },
  { name: "Джакарта",      country: "ID", popMillion: 10.6, lat: -6.2088,  lon: 106.8456 },
  { name: "Тайбэй",        country: "TW", popMillion: 2.6,  lat: 25.0330,  lon: 121.5654 },
  { name: "Катманду",      country: "NP", popMillion: 1.4,  lat: 27.7172,  lon: 85.3240 },
  { name: "Исламабад",     country: "PK", popMillion: 1.1,  lat: 33.6844,  lon: 73.0479 },
  { name: "Алматы",        country: "KZ", popMillion: 2.0,  lat: 43.2220,  lon: 76.8512 },
  { name: "Ташкент",       country: "UZ", popMillion: 2.6,  lat: 41.3111,  lon: 69.2797 },
  { name: "Бишкек",        country: "KG", popMillion: 1.1,  lat: 42.8746,  lon: 74.5698 },
  { name: "Душанбе",       country: "TJ", popMillion: 0.9,  lat: 38.5598,  lon: 68.7870 },
  { name: "Тбилиси",       country: "GE", popMillion: 1.2,  lat: 41.7151,  lon: 44.8271 },
  { name: "Баку",          country: "AZ", popMillion: 2.3,  lat: 40.4093,  lon: 49.8671 },
  { name: "Махачкала",     country: "RU", popMillion: 0.6,  lat: 42.9849,  lon: 47.5047 },
  { name: "Петропавловск-Камчатский", country: "RU", popMillion: 0.18, lat: 53.0370, lon: 158.6559 },
  { name: "Южно-Сахалинск", country: "RU", popMillion: 0.2, lat: 46.9591,  lon: 142.7380 },
  { name: "Дубай",         country: "AE", popMillion: 3.5,  lat: 25.2048,  lon: 55.2708 },
  { name: "Алеппо",        country: "SY", popMillion: 2.1,  lat: 36.2021,  lon: 37.1343 },
  { name: "Янгон",         country: "MM", popMillion: 5.5,  lat: 16.8661,  lon: 96.1951 },
  { name: "Мандалай",      country: "MM", popMillion: 1.2,  lat: 21.9588,  lon: 96.0891 },
  { name: "Крайстчерч",    country: "NZ", popMillion: 0.4,  lat: -43.5321, lon: 172.6362 },
  { name: "Каракас",       country: "VE", popMillion: 2.9,  lat: 10.4806,  lon: -66.9036 },
  { name: "Сан-Франциско", country: "US", popMillion: 0.9,  lat: 37.7749,  lon: -122.4194 },
  { name: "Лос-Анджелес",  country: "US", popMillion: 12.5, lat: 34.0522,  lon: -118.2437 },
  { name: "Каир",          country: "EG", popMillion: 9.5,  lat: 30.0444,  lon: 31.2357 },
  { name: "Карачи",        country: "PK", popMillion: 16.1, lat: 24.8607,  lon: 67.0011 },
];

// ── Company sites (fallback; primary source is the DB table) ───────────────
export const FALLBACK_SITES = [
  { name: "Tokyo Office",       siteType: "office",    latitude: 35.6762,  longitude: 139.6503,  country: "JP" },
  { name: "Istanbul Warehouse", siteType: "warehouse", latitude: 41.0082,  longitude: 28.9784,   country: "TR" },
  { name: "Dubai HQ",           siteType: "office",    latitude: 25.2048,  longitude: 55.2708,   country: "AE" },
  { name: "Santiago Office",    siteType: "office",    latitude: -33.4489, longitude: -70.6693,  country: "CL" },
  { name: "Manila Partner",     siteType: "partner",   latitude: 14.5995,  longitude: 120.9842,  country: "PH" },
  { name: "Almaty Warehouse",   siteType: "warehouse", latitude: 43.2220,  longitude: 76.8512,   country: "KZ" },
  { name: "Tehran Partner",     siteType: "partner",   latitude: 35.6892,  longitude: 51.3890,   country: "IR" },
  { name: "Mexico City Office", siteType: "office",    latitude: 19.4326,  longitude: -99.1332,  country: "MX" },
];

// ── Notable demo events ────────────────────────────────────────────────────
export const NOTABLE_EVENTS = [
  { key: "turkey2023",  id: "us6000jllz", label: "Турция, Кахраманмараш", mag: 7.8, date: "06.02.2023", note: "Надвиг/сдвиг на Восточно-Анатолийском разломе" },
  { key: "morocco2023", id: "us7000kufc", label: "Марокко, Высокий Атлас",  mag: 6.8, date: "08.09.2023", note: "Через 7 мес. после Турции, та же плита (AF)" },
  { key: "japan2024",   id: "us6000m0xl", label: "Япония, п-ов Ното",       mag: 7.5, date: "01.01.2024", note: "Обратный надвиг у побережья Японского моря" },
  { key: "taiwan2024",  id: "us7000m9g4", label: "Тайвань, Хуалянь",        mag: 7.4, date: "02.04.2024", note: "Надвиг в зоне Рюкю-Манильской коллизии" },
  { key: "myanmar2025", id: "us7000pn9s", label: "Мьянма, Сагайн",          mag: 7.7, date: "28.03.2025", note: "Сдвиг вдоль разлома Сагайн" },
];

// ── Explanation texts (answering the methodology questions) ────────────────
export const DISCLAIMER_AFTERSHOCK =
  "Оценка основана на модели Ризенберга–Джонса с типовыми (generic) параметрами, " +
  "не откалиброванными по конкретному региону. Реальное число афтершоков может " +
  "существенно отличаться. Не является официальным прогнозом.";

export const DISCLAIMER_STRESS =
  "Статистическая оценка основана на ограниченной выборке исторических данных. " +
  "Корреляция между событиями не доказывает причинно-следственную связь. " +
  "Полный расчёт переноса напряжений Кулона требует трёхмерной геометрии разломов. " +
  "Вероятности не откалиброваны. Не является официальным прогнозом.";

export const DISCLAIMER_REGIONAL =
  "Прогноз основан на статистической частоте исторических последовательностей, " +
  "а не на физической модели передачи напряжений. Учитывается только принадлежность " +
  "к общей плитной системе и временное окно. Вероятности не калиброваны и не " +
  "валидированы. Не предназначен для принятия решений о безопасности.";

export const EXPLAIN_EXPECTED_COUNT =
  "Числа в таблице — математическое ожидание количества событий (сколько событий " +
  "данной магнитуды или сильнее модель в среднем ожидает за период). " +
  "Например, «913.7» при M≥3 за год означает, что модель прогнозирует в среднем " +
  "≈914 афтершоков магнитудой от 3. Рядом приводится вероятность хотя бы одного " +
  "такого события, вычисленная по пуассоновской модели: P = 1 − e^(−N). " +
  "Так ожидание 0.9 превращается в вероятность ≈59%.";

export const EXPLAIN_TIMESTAMP =
  "Полные метки времени USGS имеют вид 2023-02-06T01:17:34.342000+00:00 — " +
  "это миллисекунды (.342) и смещение часового пояса (+00:00 = UTC). " +
  "Для бизнес-анализа точность до долей секунды не нужна, поэтому в интерфейсе " +
  "время форматируется до минут; исходное значение сохраняется в данных.";
