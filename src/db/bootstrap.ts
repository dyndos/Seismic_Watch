/**
 * DB bootstrap & data-access helpers.
 *
 * Tables are created idempotently at runtime (CREATE TABLE IF NOT EXISTS) so
 * the app works on a fresh PostgreSQL without a migration step; the drizzle
 * schema in schema.ts mirrors this DDL for `drizzle-kit push`.
 */

import { sql } from "drizzle-orm";
import { db } from "./index";
import { analyses, companySites, syncLogs } from "./schema";
import { FALLBACK_SITES } from "@/lib/data";
import type { AnalysisResult, SiteRef } from "@/lib/types";

const DDL = `
CREATE TABLE IF NOT EXISTS analyses (
  key text PRIMARY KEY,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS company_sites (
  id serial PRIMARY KEY,
  name text NOT NULL,
  site_type text NOT NULL DEFAULT 'office',
  latitude real NOT NULL,
  longitude real NOT NULL,
  country text,
  contact text
);
CREATE TABLE IF NOT EXISTS exposure_cache (
  city text PRIMARY KEY,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sync_logs (
  id serial PRIMARY KEY,
  source text NOT NULL,
  status text NOT NULL,
  records integer,
  error text,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_started ON sync_logs (started_at DESC);
`;

let bootstrapPromise: Promise<void> | null = null;

export function ensureSchema(): Promise<void> {
  if (!bootstrapPromise) {
    bootstrapPromise = (async () => {
      await db.execute(sql.raw(DDL));
      // seed company sites once
      const count = (await db.execute(sql`SELECT count(*)::int AS c FROM company_sites`)).rows[0]?.c as
        | number
        | undefined;
      if ((count ?? 0) === 0) {
        for (const s of FALLBACK_SITES) {
          await db.insert(companySites).values({
            name: s.name,
            siteType: s.siteType,
            latitude: s.latitude,
            longitude: s.longitude,
            country: s.country,
          });
        }
      }
    })().catch((e) => {
      bootstrapPromise = null; // retry next time
      throw e;
    });
  }
  return bootstrapPromise;
}

export async function getSites(): Promise<SiteRef[]> {
  try {
    await ensureSchema();
    const rows = await db.select().from(companySites);
    return rows.map((r) => ({
      name: r.name,
      siteType: r.siteType,
      latitude: r.latitude,
      longitude: r.longitude,
      country: r.country,
      contact: r.contact,
    }));
  } catch {
    return FALLBACK_SITES.map((s) => ({ ...s, country: s.country ?? null, contact: null }));
  }
}

export async function getCachedAnalysis(key: string): Promise<AnalysisResult | null> {
  try {
    await ensureSchema();
    const rows = await db.select().from(analyses).where(sql`key = ${key}`).limit(1);
    return (rows[0]?.payload as AnalysisResult) ?? null;
  } catch {
    return null;
  }
}

export async function saveAnalysis(key: string, payload: AnalysisResult): Promise<void> {
  try {
    await ensureSchema();
    await db
      .insert(analyses)
      .values({ key, payload })
      .onConflictDoUpdate({ target: analyses.key, set: { payload } });
  } catch {
    // cache failure is non-fatal
  }
}

export async function listRecentAnalyses(limit = 8): Promise<{ key: string; place: string; mag: number | null; time: string }[]> {
  try {
    await ensureSchema();
    const rows = await db.execute(sql`
      SELECT key,
             payload->'event'->>'place' AS place,
             (payload->'event'->>'magnitude')::float AS mag,
             payload->'event'->>'time' AS time
      FROM analyses
      ORDER BY created_at DESC
      LIMIT ${limit}
    `);
    return rows.rows.map((r) => ({
      key: r.key as string,
      place: (r.place as string) ?? "",
      mag: (r.mag as number) ?? null,
      time: (r.time as string) ?? "",
    }));
  } catch {
    return [];
  }
}

export async function logSync(source: string, status: string, records?: number, error?: string) {
  try {
    await ensureSchema();
    await db.insert(syncLogs).values({
      source,
      status,
      records: records ?? null,
      error: error ?? null,
      finishedAt: new Date(),
    });
  } catch {
    // non-fatal
  }
}
