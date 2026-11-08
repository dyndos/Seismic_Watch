"""Create an interactive Leaflet map from a frozen K0-K4 forecast archive.

Usage:
  python -m research.render_forecast_map --input path/to/unzipped/archive --output path/to/map.html

The archive must contain forecast_summary.json, grid.json and
forecast_snapshots/*.npz plus matching snapshot metadata JSON files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

MODELS = ("K0", "K1", "K2", "K3", "K4")
HORIZONS = (1, 3, 7, 14, 30, 90, 180, 365)


def build(input_dir: Path, output_html: Path, output_geojson: Path) -> None:
    summary = json.loads((input_dir / "forecast_summary.json").read_text(encoding="utf-8"))
    grid = json.loads((input_dir / "grid.json").read_text(encoding="utf-8"))
    cells = [{"id": c["cell_id"], "lat": round(float(c["latitude"]), 4),
              "lon": round(float(c["longitude"]), 4)} for c in grid]
    cases, layers, features = {}, {}, []
    for case_id, case in summary["cases"].items():
        meta_files = list((input_dir / "forecast_snapshots").glob(
            f"{case_id}_forecast_asof_*.json"))
        if not meta_files:
            raise FileNotFoundError(f"Snapshot metadata missing for {case_id}")
        meta = json.loads(meta_files[0].read_text(encoding="utf-8"))
        npz_path = input_dir / meta["snapshot_npz"]
        probabilities = np.load(npz_path)["probability"]
        if probabilities.shape != (5, 8, len(grid)):
            raise ValueError(f"Unexpected forecast shape for {case_id}: {probabilities.shape}")
        cases[case_id] = {
            "name": case.get("event", {}).get("place", case_id),
            "event": case["event"],
            "forecast_start": case.get("forecast_start_utc"),
        }
        for mi, model in enumerate(MODELS):
            for hi, days in enumerate(HORIZONS):
                values = probabilities[mi, hi]
                valid = np.isfinite(values)
                order = np.flatnonzero(valid)
                order = order[np.argsort(values[order])[::-1]]
                top = [{"lat": cells[int(i)]["lat"], "lon": cells[int(i)]["lon"],
                        "p": float(values[int(i)]), "id": cells[int(i)]["id"]}
                       for i in order[:10]]
                layers[f"{case_id}|{model}|{days}"] = {
                    "v": [None if not np.isfinite(x) else round(float(x), 7) for x in values],
                    "top": top,
                }
                for i in order:
                    c = grid[int(i)]
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point",
                                     "coordinates": [float(c["longitude"]), float(c["latitude"])]},
                        "properties": {"case_id": case_id, "model": model,
                                       "horizon_days": days, "cell_id": c["cell_id"],
                                       "probability": float(values[int(i)])},
                    })

    payload = json.dumps({"models": MODELS, "horizons": HORIZONS, "cells": cells,
                          "cases": cases, "layers": layers},
                         ensure_ascii=False, separators=(",", ":"))
    html = _HTML.replace("__DATA__", payload)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(html, encoding="utf-8")
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(
        {"type": "FeatureCollection", "features": features},
        separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"Interactive map: {output_html}")
    print(f"GeoJSON: {output_geojson}; {len(features)} cell forecasts")


_HTML = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Seismic Watch — K0-K4 forecast map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
body{margin:0;font:14px system-ui;color:#172033;background:#f5f7fa}header{padding:14px 18px;background:#172b4d;color:white}
h1{font-size:20px;margin:0 0 5px}.sub{font-size:12px;color:#dbe6f5}
.controls{display:flex;gap:12px;flex-wrap:wrap;padding:12px 16px;background:white}
label{font-size:12px;color:#475569;display:flex;flex-direction:column;gap:4px}
select{padding:8px;border:1px solid #cbd5e1;border-radius:7px;background:white;min-width:170px}
#map{height:65vh;min-height:430px}.panel{padding:12px 16px;background:white;margin:12px;border-radius:10px}
.note{font-size:13px;line-height:1.5;color:#475569}.warn{color:#9a3412;background:#fff7ed;border-left:3px solid #fb923c;padding:10px 12px}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:7px;border-bottom:1px solid #e2e8f0;text-align:left}
</style></head><body>
<header><h1>Seismic Watch — карта прогнозов K0–K4</h1>
<div class="sub">Зафиксированный архив · сетка 2 001 ячейка · M≥6,5</div></header>
<div class="controls">
<label>Событие<select id="case"></select></label><label>Модель<select id="model"></select></label>
<label>Горизонт<select id="days"></select></label>
<label>Слой<select id="mode"><option value="all">Все ячейки</option><option value="top">50 лидирующих ячеек</option></select></label>
</div><div id="map"></div>
<div class="panel"><b id="headline"></b><p class="note">
Кружок — центр расчетной ячейки номинальной площадью около 250 000 км². Цвет и размер показывают
вероятность хотя бы одного M≥6,5 в ячейке за выбранный горизонт. Нажмите на кружок для точного значения.
Маркер-звезда — исходное землетрясение-триггер. Название ближайшего города не является прогнозом места толчка.
</p></div>
<div class="panel"><h3>Лидирующие ячейки</h3><div id="top"></div></div>
<div class="panel warn"><b>Ограничение интерпретации.</b> Это глобальные вероятностные поверхности, а не прогноз эпицентра.
В архиве максимумы могут находиться далеко от исходного события. Не используйте цвет карты как оценку риска
для конкретного населенного пункта без отдельной пространственной калибровки.</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const D=__DATA__, map=L.map('map',{preferCanvas:true}).setView([10,145],2);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
{maxZoom:8,attribution:'© OpenStreetMap'}).addTo(map);
const $=id=>document.getElementById(id), group=L.layerGroup().addTo(map);
for(const [id,c] of Object.entries(D.cases)){let o=document.createElement('option');o.value=id;o.textContent=c.name;$('case').append(o)}
for(const m of D.models){let o=document.createElement('option');o.value=m;o.textContent=m;$('model').append(o)}
for(const d of D.horizons){let o=document.createElement('option');o.value=d;o.textContent=d+' дней';$('days').append(o)}
$('days').value='90';let trigger;
function color(p){return p>=.1?'#7f1d1d':p>=.05?'#c2410c':p>=.02?'#ea580c':p>=.01?'#d97706':p>=.005?'#eab308':p>=.001?'#65a30d':'#2563eb'}
function pct(p){return (100*p).toFixed(4)+'%'}
function draw(){
 group.clearLayers();if(trigger)map.removeLayer(trigger);
 const cid=$('case').value,m=$('model').value,d=+$('days').value,Ly=D.layers[cid+'|'+m+'|'+d],ev=D.cases[cid].event;
 let ranked=Ly.v.map((p,i)=>({p,i})).filter(x=>x.p!==null).sort((a,b)=>b.p-a.p);
 let chosen=$('mode').value==='top'?ranked.slice(0,50):ranked;
 for(const x of chosen){let c=D.cells[x.i];L.circleMarker([c.lat,c.lon],
 {radius:Math.max(3,Math.min(17,3+Math.sqrt(x.p)*35)),color:color(x.p),weight:1,fillOpacity:.62})
 .bindPopup('<b>'+m+' · '+d+' дней</b><br>Ячейка '+c.id+'<br>Центр: '+c.lat.toFixed(3)+', '+c.lon.toFixed(3)+
 '<br><b>P: '+pct(x.p)+'</b>').addTo(group)}
 trigger=L.marker([ev.latitude,ev.longitude]).bindPopup('<b>Триггер</b><br>'+ev.place+
 '<br>M'+ev.magnitude+' · '+ev.time_utc).addTo(map);
 $('headline').textContent=D.cases[cid].name+' · '+m+' · '+d+' дней · максимум ячейки '+pct(ranked[0].p);
 $('top').innerHTML='<table><tr><th>№</th><th>Центр ячейки</th><th>Вероятность</th></tr>'+
 Ly.top.map((x,i)=>'<tr><td>'+(i+1)+'</td><td>'+x.lat.toFixed(3)+', '+x.lon.toFixed(3)+'</td><td>'+pct(x.p)+'</td></tr>').join('')+'</table>';
}
['case','model','days','mode'].forEach(id=>$(id).addEventListener('change',draw));draw();
</script></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("forecast-map.html"))
    parser.add_argument("--geojson", type=Path, default=Path("forecast_cells.geojson"))
    args = parser.parse_args()
    build(args.input, args.output, args.geojson)


if __name__ == "__main__":
    main()
