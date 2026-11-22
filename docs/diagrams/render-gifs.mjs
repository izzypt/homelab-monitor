// Render GIF copies of the animated flow SVGs (for slides, chats, or viewers without SVG animation).
//
//   python3 docs/diagrams/build.py          # regenerate the SVGs first
//   NODE_PATH=$(npm root -g) node docs/diagrams/render-gifs.mjs   # needs playwright (Chromium) and ffmpeg
//
// Each SVG is a SMIL animation, so frames are taken deterministically with setCurrentTime().
// Optional: --png writes one still per step to /tmp for quick review instead of GIFs.

import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

// CommonJS require honours NODE_PATH, so a global install works: NODE_PATH=$(npm root -g)
const { chromium } = createRequire(import.meta.url)("playwright");
const here = dirname(fileURLToPath(import.meta.url));
const flowsDir = join(here, "flows");
const outDir = join(here, "gif");
const FPS = 10;
const WIDTH = 960; // output width in pixels; the SVG is scaled down from 1240
const stills = process.argv.includes("--png");

mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });

for (const file of readdirSync(flowsDir).filter((f) => f.endsWith(".svg"))) {
  const svg = readFileSync(join(flowsDir, file), "utf8");
  const [, w, h] = svg.match(/viewBox="0 0 (\d+) (\d+)"/).map(Number);
  const height = Math.round((h * WIDTH) / w);
  await page.setViewportSize({ width: WIDTH, height });
  await page.setContent(
    `<html><body style="margin:0;background:#fff">${svg.replace(/width="\d+" height="\d+"/, `width="${WIDTH}" height="${height}"`)}</body></html>`,
  );
  // Loop length = the dur of any animate element.
  const total = await page.evaluate(() => {
    const svgEl = document.querySelector("svg");
    svgEl.pauseAnimations();
    return parseFloat(document.querySelector("animate").getAttribute("dur"));
  });
  const name = basename(file, ".svg");
  const frames = mkdtempSync(join(tmpdir(), `flow-${name}-`));
  const times = stills
    ? [...Array(Math.floor(total / 2.6)).keys()].map((i) => 0.4 + i * 2.6 + 0.9)
    : [...Array(Math.round(total * FPS)).keys()].map((i) => i / FPS);
  for (const [i, t] of times.entries()) {
    await page.evaluate((time) => document.querySelector("svg").setCurrentTime(time), t);
    await page.screenshot({ path: join(frames, `f${String(i).padStart(4, "0")}.png`) });
  }
  if (stills) {
    console.log(`${name}: stills in ${frames}`);
    continue;
  }
  const gif = join(outDir, `${name}.gif`);
  execFileSync("ffmpeg", [
    "-y", "-loglevel", "error", "-framerate", String(FPS), "-i", join(frames, "f%04d.png"),
    "-vf", "split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle",
    "-loop", "0", gif,
  ]);
  rmSync(frames, { recursive: true });
  console.log(`docs/diagrams/gif/${name}.gif`);
}
await browser.close();
