"""Render human-readable geography and probability summaries for K0-K4 forecasts.

Uses OpenStreetMap Nominatim reverse geocoding with a local cache. The raw
forecast probabilities remain unchanged. This is a presentation layer only.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "SeismicWatchResearch/0.2 (forecast geography labels)"
SETTLEMENT_KEYS = ("city", "town", "village", "hamlet", "municipality", "suburb")
REGION_KEYS = ("state", "province", "county", "region", "state_district")
WATER_KEYS = ("sea", "ocean", "bay", "gulf", "strait", "waterway")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def reverse_geocode(lat: float, lon: float, cache: dict[str, Any],
                    session: requests.Session) -> dict[str, Any]:
    key = f"{lat:.4f},{lon:.4f}"
    if key in cache:
        return cache[key]
    try:
        response = session.get(
            NOMINATIM_URL,
            params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10,
                    "addressdetails": 1, "namedetails": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        address = payload.get("address") or {}
        settlement = next((address.get(k) for k in SETTLEMENT_KEYS if address.get(k)), None)
        region = next((address.get(k) for k in REGION_KEYS if address.get(k)), None)
        country = address.get("country")
        named = payload.get("name") or (payload.get("namedetails") or {}).get("name")
        water = next((address.get(k) for k in WATER_KEYS if address.get(k)), None)
        # Do not infer a sea/ocean name from coordinates. If OSM does not identify
        # one, report the open-water location and retain coordinates for the map.
        if water or (named and any(word in str(named).lower() for word in
                                  ("sea", "ocean", "gulf", "bay", "strait"))):
            place = str(water or named)
            label = f"{place} (акватория)"
            kind = "water"
        elif settlement:
            label = ", ".join(x for x in (str(settlement), str(region) if region else None,
                                           str(country) if country else None) if x)
            place = str(settlement)
            kind = "settlement"
        elif country:
            label = ", ".join(x for x in (str(region) if region else None, str(country)) if x)
            place = str(region or country)
            kind = "country_or_region"
        else:
            label = f"Открытая акватория / неразмеченная территория ({lat:.2f}, {lon:.2f})"
            place = None
            kind = "unresolved"
        result = {
            "label": label, "place": place, "settlement": settlement,
            "region": region, "country": country, "water_body": water,
            "kind": kind, "osm_display_name": payload.get("display_name"),
            "latitude": lat, "longitude": lon,
            "geocoding_source": "OpenStreetMap Nominatim",
        }
    except (requests.RequestException, ValueError, KeyError) as exc:
        result = {
            "label": f"Место не определено ({lat:.2f}, {lon:.2f})",
            "place": None, "settlement": None, "region": None, "country": None,
            "water_body": None, "kind": "unresolved", "latitude": lat,
            "longitude": lon, "geocoding_source": "unavailable",
            "geocoding_error": str(exc),
        }
    cache[key] = result
    # Nominatim public service policy: do not exceed one request per second.
    time.sleep(1.05)
    return result


def bar(probability: float, width: int = 20) -> str:
    value = max(0.0, min(1.0, probability))
    filled = min(width, int(round(value * width)))
    return "█" * filled + "░" * (width - filled)


def pct(probability: float | None) -> str:
    return "н/д" if probability is None else f"{100.0 * probability:.4f}%"


def local_probability(cells: list[dict[str, Any]], probabilities: list[float],
                      lat: float, lon: float, radius_km: float = 1000.0) -> float | None:
    selected = []
    for cell, p in zip(cells, probabilities):
        if not math.isfinite(float(p)):
            continue
        p1, p2 = math.radians(lat), math.radians(float(cell["latitude"]))
        dlat = p2 - p1
        dlon = math.radians((float(cell["longitude"]) - lon + 180) % 360 - 180)
        a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
        distance = 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(a)))
        if distance <= radius_km:
            selected.append(max(0.0, min(1.0, float(p))))
    if not selected:
        return None
    return 1.0 - math.prod(1.0 - p for p in selected)


def run(output_dir: Path) -> tuple[Path, Path]:
    summary = read_json(output_dir / "forecast_summary.json")
    cells = read_json(output_dir / "grid.json")
    cell_by_id = {str(c["cell_id"]): c for c in cells}
    cache_path = output_dir / "geocode_cache.json"
    cache = read_json(cache_path) if cache_path.exists() else {}
    session = requests.Session()

    geo_features: list[dict[str, Any]] = []
    report = [
        "# Seismic Watch — географически размеченный прогноз K0–K4", "",
        f"**Дата фиксации:** {summary.get('forecast_created_utc', 'не указана')}", "",
        "**Что означает вероятность.** Значение в строке относится к одной ячейке сетки "
        "номинальным размером около 500 км: вероятность хотя бы одного события M≥6,5 "
        "в этой ячейке за указанный горизонт. Это не вероятность землетрясения в "
        "названном городе и не вероятность события в радиусе вокруг города.", "",
        "Шкала рядом с процентом — визуальная шкала от 0 до 100% для самой ячейки; "
        "при малых вероятностях она закономерно почти пустая. Число всегда важнее длины полосы.", "",
        "## Сводка по территориям", "",
    ]

    for case_id, case in summary.get("cases", {}).items():
        event = case["event"]
        snapshot_meta_path = output_dir / "forecast_snapshots" / f"{case_id}.json"
        snapshot_meta = read_json(snapshot_meta_path) if snapshot_meta_path.is_file() else {}
        snapshot_npz_name = snapshot_meta.get("snapshot_npz")
        trigger_geo = reverse_geocode(float(event["latitude"]), float(event["longitude"]), cache, session)
        report.extend([
            f"### {case.get('event_name', case_id)}",
            f"- **Очаг:** {trigger_geo['label']}",
            f"- **Координаты:** {event['latitude']:.3f}°, {event['longitude']:.3f}°; "
            f"глубина {event.get('depth_km')} км; M{event.get('magnitude')}",
            f"- **Начало прогноза:** {case.get('forecast_start_utc')}",
            f"- **Горизонты:** 1, 3, 7, 14, 30, 90 и 365 суток",
            "",
            "| Модель | 7 дней: P в ячейке-лидере | 30 дней | 90 дней | 365 дней | P≥1 события в радиусе 1000 км за 90 дней* |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        case_geo = []
        for model, model_data in case.get("models", {}).items():
            horizons = {int(x["days"]): x for x in model_data.get("horizons", [])}
            leader_probs = {}
            for day, horizon in horizons.items():
                top = horizon.get("top_cells") or []
                if top:
                    leader_probs[day] = float(top[0]["probability"])
                    for rank, item in enumerate(top[:5], start=1):
                        cell = cell_by_id.get(str(item.get("cell_id")), item)
                        lat, lon = float(cell["latitude"]), float(cell["longitude"])
                        location = reverse_geocode(lat, lon, cache, session)
                        feature = {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [lon, lat]},
                            "properties": {
                                "case_id": case_id, "model": model, "horizon_days": day,
                                "rank": rank, "probability": float(item["probability"]),
                                "cell_id": item.get("cell_id"), **location,
                            },
                        }
                        geo_features.append(feature)
                        if day == 90:
                            case_geo.append((model, rank, float(item["probability"]), location))
            local90 = None
            h90 = horizons.get(90)
            if h90:
                # This is an independence approximation over cells, not a calibrated
                # regional event probability.
                npz_path = output_dir / snapshot_npz_name if snapshot_npz_name else Path("/__missing_snapshot__")
                if npz_path.is_file():
                    import numpy as np
                    with np.load(npz_path, allow_pickle=False) as npz:
                        mi = ("K0", "K1", "K2", "K3", "K4").index(model)
                        hi = (1, 3, 7, 14, 30, 90, 180, 365).index(90)
                        local90 = local_probability(cells, npz["probability"][mi, hi].astype(float).tolist(),
                                                    float(event["latitude"]), float(event["longitude"]))
            report.append(
                f"| {model} | {pct(leader_probs.get(7))} | {pct(leader_probs.get(30))} | "
                f"{pct(leader_probs.get(90))} | {pct(leader_probs.get(365))} | "
                f"{pct(local90)} |"
            )
        report.extend(["", "#### Наиболее вероятные территории на горизонте 90 дней", "",
                       "| Модель | Ранг | Территория / ближайший населенный пункт | Вероятность ячейки |",
                       "|---|---:|---|---:|"])
        max_cell_probability = max((item[2] for item in case_geo), default=0.0)
        report.append("Полоса показывает относительную величину среди лидирующих ячеек "
                      "этого прогноза (максимум = 100%); рядом указана абсолютная вероятность.")
        for model, rank, probability, location in case_geo:
            relative = probability / max_cell_probability if max_cell_probability > 0 else 0.0
            report.append(f"| {model} | {rank} | {location['label']} | "
                          f"{pct(probability)} {bar(relative)} |")
        report.extend([
            "", "* Региональная оценка для радиуса 1000 км — приближение через произведение "
            "вероятностей ячеек при предположении их независимости. Это не откалиброванная "
            "вероятность и не прогноз для населенного пункта.", "",
        ])

    report.extend([
        "## Сопоставление моделей",
        "",
        "K0 — базовая историческая частота; K1 — кинематические признаки плит; "
        "K2 — дополнительные Coupling Cloud и Slab2; K3 — шаг статического изменения "
        "напряжения Кулона; K4 — Dieterich rate-and-state.",
        "",
        "Различия между K0–K4 следует читать как диапазон сценариев. Если оценки близки, "
        "модели согласны; если заметно расходятся, это неопределенность, а не основание "
        "автоматически выбирать максимальную оценку.",
        "",
        "## Ограничения географической подписи",
        "",
        "Подписи получены обратным геокодированием OpenStreetMap Nominatim. Для точек "
        "в открытом море, где источник не вернул название водного объекта, отчет "
        "не выдумывает название моря/океана и сохраняет координаты для карты.",
        "Точки лидеров относятся к центрам ячеек размером около 500 км; подпись города "
        "или региона — географический ориентир, а не точное место будущего землетрясения.",
        "",
        "## Данные для карты",
        "",
        "Файл forecast_locations.geojson содержит центры топ-ячеек для всех моделей, "
        "горизонтов и кейсов, с вероятностью, рангом и географической подписью. "
        "Его можно подключить к Leaflet/MapLibre в следующем UI-этапе.",
        "",
    ])
    report_path = output_dir / "report-visual-ru.md"
    geo_path = output_dir / "forecast_locations.geojson"
    report_path.write_text("\n".join(report), encoding="utf-8")
    write_json(geo_path, {"type": "FeatureCollection", "features": geo_features})
    write_json(cache_path, cache)
    return report_path, geo_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="Directory containing forecast_summary.json and grid.json")
    args = parser.parse_args()
    report, geojson = run(args.output)
    print(f"Visual report: {report}")
    print(f"Map data: {geojson}")


if __name__ == "__main__":
    main()
