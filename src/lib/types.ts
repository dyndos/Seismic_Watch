/**
 * Shared domain types for Seismic Watch.
 */

export type FaultType = "strike_slip" | "thrust" | "normal" | "oblique" | "unknown";

export interface QuakeEvent {
  id: string;
  magnitude: number | null;
  magType: string | null;
  place: string;
  time: string; // ISO 8601 UTC
  latitude: number;
  longitude: number;
  depthKm: number | null;
  tsunami: boolean;
  alert: string | null;
  url?: string | null;
  source: "usgs" | "manual";
}

export interface FocalMechanism {
  np1Strike: number | null;
  np1Dip: number | null;
  np1Rake: number | null;
  np2Strike: number | null;
  np2Dip: number | null;
  np2Rake: number | null;
  scalarMoment: number | null;
  pctDoubleCouple: number | null;
  faultType: FaultType;
  slipAzimuth: number | null;
  compressionAzimuth: number | null;
  tensorSource: string | null;
}

export interface BoundaryInfo {
  distanceKm: number;
  name: string;
  plates: string[];
  plateNames: string[];
  boundaryType: string | null; // 'subduction' | '' from PB2002
}

export interface SiteRef {
  name: string;
  siteType: string;
  latitude: number;
  longitude: number;
  country?: string | null;
  contact?: string | null;
}

export interface SiteHit extends SiteRef {
  distanceKm: number;
}

export interface CityHit {
  name: string;
  country: string;
  popMillion: number;
  lat: number;
  lon: number;
  distanceKm: number;
}

export interface HistStats {
  years: number;
  radiusKm: number;
  minMag: number;
  total: number;
  bins: { label: string; count: number }[];
  maxMag: number | null;
  maxEvent: { id: string; place: string; time: string; magnitude: number } | null;
  annualRate: number; // events/year at M>=minMag
  recent12m: number; // events in last 12 months before trigger
}

export interface AftershockCell {
  expected: number | null; // mathematical expectation of count
  probability: number | null; // P(>=1 event) under Poisson
}

export interface AftershockWindow {
  label: string;
  days: number;
  cells: Record<string, AftershockCell>; // keys 'M3' | 'M4' | 'M5' | 'M6'
}

export interface AftershockForecast {
  model: string;
  params: { a: number; b: number; c: number; p: number };
  mainMag: number;
  windows: AftershockWindow[];
}

export interface HorizonResult {
  months: number;
  triggered: number;
  total: number;
  percentage: number;
  pending?: boolean;
}

export interface RegionalForecast {
  status: "ok" | "insufficient_data" | "no_plates";
  message?: string;
  triggerMag: number;
  triggerPlates: string[];
  triggerPlateNames: string[];
  triggerMinMag: number;
  minRemoteMag: number;
  minDistanceKm: number;
  sampleSize: number;
  catalogSize: number;
  results: Record<string, HorizonResult>;
  topRegions: { region: string; count: number }[];
}

export interface ValidationHorizon {
  months: number;
  predictedPct: number;
  basedOn: number; // historical triggers used
  observed: "yes" | "no" | "pending";
  observedEvents: { id: string; place: string; magnitude: number; daysAfter: number }[];
  coveragePct: number; // fraction of horizon covered by catalog (100 for past events)
}

export interface ValidationResult {
  status: "ok" | "insufficient_data";
  message?: string;
  trainingYears: number;
  horizons: ValidationHorizon[];
  summary: string;
}

export interface SequenceItem {
  id: string;
  time: string;
  magnitude: number;
  place: string;
  region: string;
  latitude: number;
  longitude: number;
  distanceKm: number;
  daysAfter: number;
  sameSystem: boolean;
  plates: string[];
}

export interface MapAftershock {
  id: string;
  latitude: number;
  longitude: number;
  magnitude: number;
  depthKm: number | null;
  time: string;
  place: string;
}

export interface ManualSpec {
  latitude: number;
  longitude: number;
  magnitude: number;
  depthKm?: number;
  place?: string;
  faultType?: FaultType;
  slipAzimuth?: number;
}

export interface AnalysisResult {
  key: string;
  modelVersion: number;
  generatedAt: string;
  event: QuakeEvent;
  focal: FocalMechanism | null;
  boundary: BoundaryInfo | null;
  nearbySites: SiteHit[];
  nearbyCities: CityHit[];
  history: HistStats | null;
  aftershock: AftershockForecast | null;
  regional: RegionalForecast | null;
  validation: ValidationResult | null;
  sequence: SequenceItem[];
  aftershocks30d: MapAftershock[];
  isManual: boolean;
}
