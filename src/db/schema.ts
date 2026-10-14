import { integer, jsonb, pgTable, real, serial, text, timestamp } from "drizzle-orm/pg-core";
import type { AnalysisResult } from "@/lib/types";

export const analyses = pgTable("analyses", {
  key: text("key").primaryKey(),
  payload: jsonb("payload").$type<AnalysisResult>().notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
});

export const companySites = pgTable("company_sites", {
  id: serial("id").primaryKey(),
  name: text("name").notNull(),
  siteType: text("site_type").notNull().default("office"),
  latitude: real("latitude").notNull(),
  longitude: real("longitude").notNull(),
  country: text("country"),
  contact: text("contact"),
});

export const exposureCache = pgTable("exposure_cache", {
  city: text("city").primaryKey(),
  payload: jsonb("payload").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
});

export const syncLogs = pgTable("sync_logs", {
  id: serial("id").primaryKey(),
  source: text("source").notNull(),
  status: text("status").notNull(),
  records: integer("records"),
  error: text("error"),
  startedAt: timestamp("started_at", { withTimezone: true }).defaultNow().notNull(),
  finishedAt: timestamp("finished_at", { withTimezone: true }),
});
