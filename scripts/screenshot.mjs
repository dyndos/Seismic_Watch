/**
 * Portfolio screenshot tool.
 *
 * Usage:
 *   1. Start the app:        npm run build && npm start   (или docker compose up)
 *   2. Install the driver:   npm i -D puppeteer
 *   3. Run:                  node scripts/screenshot.mjs
 *
 * Output: docs/screenshots/*.png  (referenced from README.md)
 * Tip: run the Turkey analysis once first so the result is cached and the
 * analysis page loads instantly.
 */
import puppeteer from "puppeteer";
import { mkdir } from "fs/promises";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const OUT = "docs/screenshots";

const shots = [
  { name: "01-dashboard", url: "/", wait: 2500 },
  { name: "02-analysis-header", url: "/analysis/us6000jllz", waitFor: ".leaflet-container", wait: 6000 },
  { name: "03-analysis-map", url: "/analysis/us6000jllz", waitFor: ".leaflet-container", wait: 8000, scrollTo: "#map" },
  { name: "04-analysis-forecast", url: "/analysis/us6000jllz", waitFor: ".leaflet-container", wait: 6000, scrollTo: "#regional" },
  { name: "05-analysis-validation", url: "/analysis/us6000jllz", waitFor: ".leaflet-container", wait: 6000, scrollTo: "#validation" },
  { name: "06-exposure", url: "/exposure", wait: 6000 },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

await mkdir(OUT, { recursive: true });
const browser = await puppeteer.launch({
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"],
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });

  for (const s of shots) {
    console.log(`→ ${s.name}  ${s.url}`);
    await page.goto(`${BASE}${s.url}`, { waitUntil: "networkidle2", timeout: 120_000 });
    if (s.waitFor) {
      await page.waitForSelector(s.waitFor, { timeout: 120_000 }).catch(() => {
        console.warn(`   (selector ${s.waitFor} not appeared, shooting anyway)`);
      });
    }
    await sleep(s.wait ?? 2000);
    if (s.scrollTo) {
      await page.evaluate((sel) => document.querySelector(sel)?.scrollIntoView(), s.scrollTo);
      await sleep(1200);
    }
    await page.screenshot({ path: `${OUT}/${s.name}.png` });
  }
  console.log(`Done. Images in ${OUT}/`);
} finally {
  await browser.close();
}
