// Browser QA for the parametric enclosure viewer.
import { chromium } from "playwright";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const viewer = resolve(root, "enclosure_viewer.html");
const outDir = resolve(root, "docs");
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({
  args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const consoleErrors = [];
page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });
page.on("pageerror", (err) => consoleErrors.push("pageerror: " + err.message));

await page.goto(pathToFileURL(viewer).href, { waitUntil: "load" });
await page.waitForFunction(() => window.__ENCLOSURE_STATE__ && window.__ENCLOSURE_STATE__.ready === true, null, { timeout: 20000 });
await page.waitForTimeout(700);

const initial = await page.evaluate(() => ({ ...window.__ENCLOSURE_STATE__ }));
await page.screenshot({ path: resolve(outDir, "preview.png") });

await page.click('[data-preset="vl53l1x"]');
await page.evaluate(() => {
  const explode = document.getElementById("explode");
  explode.value = "55";
  explode.dispatchEvent(new Event("input", { bubbles: true }));
});
await page.waitForTimeout(600);
const exploded = await page.evaluate(() => ({ preset: window.__ENCLOSURE_STATE__.preset, explode: window.__ENCLOSURE_STATE__.explode }));
await page.screenshot({ path: resolve(outDir, "preview-exploded.png") });

await page.evaluate(() => {
  const section = document.getElementById("section");
  section.value = "16";
  section.dispatchEvent(new Event("input", { bubbles: true }));
});
await page.waitForTimeout(500);
const section = await page.evaluate(() => ({ section: window.__ENCLOSURE_STATE__.section }));
await page.screenshot({ path: resolve(outDir, "preview-section.png") });

await page.click("#wire");
await page.waitForTimeout(400);
const wire = await page.evaluate(() => ({ wire: window.__ENCLOSURE_STATE__.wire }));
await page.screenshot({ path: resolve(outDir, "preview-wireframe.png") });

const hash = createHash("sha256").update(readFileSync(viewer)).digest("hex");
const gateText = await page.locator("#gate").textContent();
const meshText = await page.locator("#mesh-gate").textContent();
const result = {
  viewer: "enclosure_viewer.html",
  viewer_sha256: hash,
  viewport: { width: 1440, height: 900 },
  webgl: { ready: initial.ready, renderer: initial.renderer, three: initial.three },
  checks: initial.checks,
  gates: { spec: gateText?.trim(), mesh: meshText?.trim() },
  interactions: { exploded, section, wire },
  consoleErrors,
  screenshots: ["preview.png", "preview-exploded.png", "preview-section.png", "preview-wireframe.png"],
};

writeFileSync(resolve(outDir, "browser-qa.json"), JSON.stringify(result, null, 2) + "\n");
console.log(JSON.stringify(result, null, 2));
await browser.close();
