"use client";

import { useEffect, useMemo, useState } from "react";
import {
  MapContainer,
  TileLayer,
  GeoJSON,
  CircleMarker,
  Circle,
  Polyline,
  Polygon,
  Tooltip,
  Popup,
} from "react-leaflet";
import type { Feature, FeatureCollection } from "geojson";
import "leaflet/dist/leaflet.css";
import { magColor, fmtDateShort } from "@/lib/format";
import { destinationPoint } from "@/lib/geo";
import type { CityHit, MapAftershock, SequenceItem, SiteHit } from "@/lib/types";

export interface SeismicMapProps {
  center: [number, number];
  zoom?: number;
  epicenter?: { lat: number; lon: number; mag: number | null; label: string };
  slip?: { lat: number; lon: number; azimuthDeg: number; lengthKm: number } | null;
  sequence?: SequenceItem[];
  aftershocks?: MapAftershock[];
  sites?: SiteHit[];
  cities?: CityHit[];
  ringsKm?: number[];
  extraEvents?: { lat: number; lon: number; mag: number }[];
}

type Plates = FeatureCollection | null;

let platesPromise: Promise<Plates> | null = null;
function loadPlates(): Promise<Plates> {
  if (!platesPromise) {
    platesPromise = fetch("/data/plates.geojson")
      .then((r) => (r.ok ? ((r.json() as unknown) as Plates) : null))
      .catch(() => null);
  }
  return platesPromise;
}

function plateStyle(f?: Feature) {
  const t = (f?.properties as { Type?: string } | undefined)?.Type;
  return t === "subduction"
    ? { color: "#3b82f6", weight: 1.6, opacity: 0.75 }
    : { color: "#2e4a78", weight: 1.1, opacity: 0.65 };
}

export default function SeismicMap({
  center,
  zoom = 5,
  epicenter,
  slip,
  sequence = [],
  aftershocks = [],
  sites = [],
  cities = [],
  ringsKm = [500, 1000, 1500],
  extraEvents = [],
}: SeismicMapProps) {
  const [plates, setPlates] = useState<Plates>(null);
  const [boundariesOn, setBoundariesOn] = useState(true);

  useEffect(() => {
    let alive = true;
    void loadPlates().then((p) => {
      if (alive) setPlates(p);
    });
    return () => {
      alive = false;
    };
  }, []);

  const slipLine = useMemo(() => {
    if (!slip) return null;
    const [elat, elon] = destinationPoint(slip.lat, slip.lon, slip.azimuthDeg, slip.lengthKm);
    const [hlat, hlon] = destinationPoint(slip.lat, slip.lon, slip.azimuthDeg, slip.lengthKm * 0.92);
    const [w1lat, w1lon] = destinationPoint(hlat, hlon, slip.azimuthDeg + 145, slip.lengthKm * 0.1);
    const [w2lat, w2lon] = destinationPoint(hlat, hlon, slip.azimuthDeg - 145, slip.lengthKm * 0.1);
    return { tip: [elat, elon] as [number, number], line: [[slip.lat, slip.lon], [hlat, hlon]] as [number, number][], head: [[elat, elon], [w1lat, w1lon], [w2lat, w2lon]] as [number, number][] };
  }, [slip]);

  return (
    <div className="relative h-[520px] w-full overflow-hidden rounded-2xl ring-1 ring-line">
      <MapContainer center={center} zoom={zoom} scrollWheelZoom className="h-full w-full" attributionControl>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />

        {boundariesOn && plates ? <GeoJSON data={plates} style={plateStyle} /> : null}

        {/* radius rings */}
        {ringsKm.map((km) => (
          <Circle
            key={km}
            center={center}
            radius={km * 1000}
            pathOptions={{ color: "#33507a", weight: 1, dashArray: "5 7", fill: false, opacity: 0.55 }}
          >
            <Tooltip sticky direction="right" className="num text-xs">
              {km} км
            </Tooltip>
          </Circle>
        ))}

        {/* historical context (exposure mode) */}
        {extraEvents.map((e, i) => (
          <CircleMarker
            key={`x${i}`}
            center={[e.lat, e.lon]}
            radius={2.5 + Math.max(0, e.mag - 4) * 1.2}
            pathOptions={{ color: magColor(e.mag), weight: 1, fillOpacity: 0.35, fillColor: magColor(e.mag), opacity: 0.7 }}
          >
            <Tooltip className="num text-xs">M{e.mag.toFixed(1)}</Tooltip>
          </CircleMarker>
        ))}

        {/* aftershocks */}
        {aftershocks.map((a) => (
          <CircleMarker
            key={a.id}
            center={[a.latitude, a.longitude]}
            radius={Math.max(3, 2 + (a.magnitude - 4) * 1.8)}
            pathOptions={{ color: magColor(a.magnitude), weight: 1.2, fillOpacity: 0.5, fillColor: magColor(a.magnitude) }}
          >
            <Tooltip className="text-xs">
              <div className="num">M{a.magnitude.toFixed(1)} · {a.depthKm ?? "?"} км</div>
              <div className="opacity-70">{fmtDateShort(a.time)}</div>
            </Tooltip>
          </CircleMarker>
        ))}

        {/* remote sequence events */}
        {sequence.map((s) => (
          <CircleMarker
            key={s.id}
            center={seqCenter(s)}
            radius={5 + Math.max(0, s.magnitude - 6) * 3}
            pathOptions={{
              color: s.sameSystem ? "#34d399" : "#475569",
              weight: 2,
              fillOpacity: 0.45,
              fillColor: s.sameSystem ? "#34d399" : "#64748b",
              dashArray: s.sameSystem ? undefined : "3 3",
            }}
          >
            <Popup>
              <div className="text-sm">
                <div className="num font-semibold">M{s.magnitude.toFixed(1)} · {s.region}</div>
                <div className="opacity-70">{s.place}</div>
                <div className="num mt-1 text-xs opacity-80">
                  через {s.daysAfter} дн. · {s.distanceKm.toLocaleString("ru-RU")} км
                </div>
                <div className="mt-1 text-xs">
                  {s.sameSystem ? "Та же плитная система" : "Другая плитная система"}
                </div>
              </div>
            </Popup>
          </CircleMarker>
        ))}

        {/* slip direction arrow */}
        {slipLine ? (
          <>
            <Polyline positions={slipLine.line} pathOptions={{ color: "#f43f5e", weight: 3, opacity: 0.9 }} />
            <Polygon positions={slipLine.head} pathOptions={{ color: "#f43f5e", weight: 2, fillOpacity: 0.9, fillColor: "#f43f5e" }} />
          </>
        ) : null}

        {/* company sites */}
        {sites.map((s) => (
          <CircleMarker
            key={s.name}
            center={[s.latitude, s.longitude]}
            radius={6}
            pathOptions={{ color: "#c084fc", weight: 2, fillOpacity: 0.85, fillColor: "#a855f7" }}
          >
            <Tooltip className="text-xs">
              <div className="font-semibold">{s.name}</div>
              <div className="num opacity-70">{Math.round(s.distanceKm).toLocaleString("ru-RU")} км</div>
            </Tooltip>
          </CircleMarker>
        ))}

        {/* major cities */}
        {cities.map((c) => (
          <CircleMarker
            key={c.name}
            center={[c.lat, c.lon]}
            radius={7}
            pathOptions={{ color: "#e2e8f0", weight: 1.6, fillOpacity: 0.9, fillColor: "#0ea5e9" }}
          >
            <Tooltip className="text-xs">
              <div className="font-semibold">{c.name} ({c.country})</div>
              <div className="num opacity-70">
                {c.popMillion} млн · {Math.round(c.distanceKm).toLocaleString("ru-RU")} км
              </div>
            </Tooltip>
          </CircleMarker>
        ))}

        {/* epicenter */}
        {epicenter ? (
          <>
            <CircleMarker
              center={[epicenter.lat, epicenter.lon]}
              radius={16}
              pathOptions={{ color: magColor(epicenter.mag ?? 5), weight: 1.5, opacity: 0.5, fill: false }}
            />
            <CircleMarker
              center={[epicenter.lat, epicenter.lon]}
              radius={8}
              pathOptions={{ color: "#fff", weight: 2.5, fillOpacity: 0.95, fillColor: magColor(epicenter.mag ?? 5) }}
            >
              <Popup>
                <div className="text-sm">
                  <div className="num font-bold">M{(epicenter.mag ?? 0).toFixed(1)}</div>
                  <div>{epicenter.label}</div>
                </div>
              </Popup>
            </CircleMarker>
          </>
        ) : null}
      </MapContainer>

      {/* legend + toggle */}
      <div className="absolute bottom-4 left-4 z-[500] rounded-xl border border-line bg-ink/85 px-3.5 py-2.5 text-[11px] leading-relaxed text-fog backdrop-blur">
        <LegendDot color="#fb7185" label="главный толчок / M по цвету" />
        <LegendDot color="#fbbf24" label="афтершоки (30 дней)" />
        <LegendDot color="#34d399" label="удалённые события, та же система" />
        <LegendDot color="#64748b" label="события вне системы" />
        <LegendDot color="#c084fc" label="объекты компании" />
        <LegendDot color="#0ea5e9" label="крупные города" />
        <div className="mt-1.5 flex items-center gap-1.5 border-t border-line-soft pt-1.5">
          <span className="inline-block h-0.5 w-4 bg-rose-500" />
          <span>направление движения плиты</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-blue-500" />
          <button onClick={() => setBoundariesOn((v) => !v)} className="text-signal underline-offset-2 hover:underline">
            границы плит: {boundariesOn ? "вкл" : "выкл"}
          </button>
        </div>
      </div>
    </div>
  );
}

function seqCenter(s: SequenceItem): [number, number] {
  return [s.latitude, s.longitude];
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      <span>{label}</span>
    </div>
  );
}
