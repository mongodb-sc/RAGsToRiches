/**
 * Walk the Atlas National Bank Streamlit demo and capture screenshots + video.
 * Target: https://54.147.137.184.sslip.io/
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const BASE = process.env.DEMO_URL || "https://54.147.137.184.sslip.io/";
const OUT = __dirname;
const SHOTS = path.join(OUT, "screenshots");
const RECORD = path.join(OUT, ".record");

async function clickNav(page, label) {
  // Streamlit nav buttons are st.button widgets in a row.
  const btn = page.locator('button').filter({ hasText: new RegExp(`^${label}$`) }).first();
  await btn.scrollIntoViewIfNeeded();
  await btn.click({ force: true });
  await page.waitForTimeout(1800);
}

async function shot(page, name) {
  const file = path.join(SHOTS, `${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  console.log("shot", name);
  return file;
}

async function main() {
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.mkdirSync(RECORD, { recursive: true });
  for (const f of fs.readdirSync(RECORD)) {
    fs.rmSync(path.join(RECORD, f), { recursive: true, force: true });
  }

  const browser = await chromium.launch({
    headless: true,
    channel: "chrome",
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: RECORD, size: { width: 1440, height: 900 } },
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  page.setDefaultTimeout(45000);

  console.log("goto", BASE);
  await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForSelector('text=Retail Banking', { timeout: 60000 });
  await page.waitForTimeout(2500);
  await shot(page, "01-help-overview");

  // RAG tab
  await clickNav(page, "Banking RAG Assistant");
  await page.waitForTimeout(1500);
  await shot(page, "02-rag-assistant");

  // Try featured / example question if present
  const wire = page.locator('button').filter({ hasText: /wire fee|overdraft|outgoing domestic/i }).first();
  if (await wire.count()) {
    await wire.click({ force: true });
    await page.waitForTimeout(8000);
    await shot(page, "03-rag-answer");
  }

  // Knowledge Graph
  await clickNav(page, "Knowledge Graph");
  await page.waitForTimeout(1500);
  const runGraph = page.locator('button').filter({ hasText: /Run \$graphLookup|graphLookup|Run/i }).first();
  if (await runGraph.count()) {
    await runGraph.click({ force: true });
    await page.waitForTimeout(6000);
  }
  await shot(page, "04-knowledge-graph");

  // Governance
  await clickNav(page, "Governance & Security");
  await page.waitForTimeout(2000);
  await shot(page, "05-governance");

  // Agent Memory
  await clickNav(page, "Agent Memory & State");
  await page.waitForTimeout(1500);
  const prefer = page.locator('button').filter({ hasText: /email or SMS|prefer email/i }).first();
  if (await prefer.count()) {
    await prefer.click({ force: true });
    await page.waitForTimeout(12000);
  } else {
    const runAgent = page.locator('button').filter({ hasText: /Run LangGraph|Run agent|Ask/i }).first();
    if (await runAgent.count()) {
      await runAgent.click({ force: true });
      await page.waitForTimeout(12000);
    }
  }
  await shot(page, "06-agent-memory");

  // Checkpoints
  await clickNav(page, "Checkpoint Inspector");
  await page.waitForTimeout(2500);
  await shot(page, "07-checkpoints");

  // Audit & Lineage (tree)
  await clickNav(page, "Audit & Lineage");
  await page.waitForTimeout(3000);
  await shot(page, "08-audit-lineage");

  // Expand tree if iframe present
  try {
    const frame = page.frames().find((f) => f.url() === "about:blank" || f !== page.mainFrame());
    for (const f of page.frames()) {
      const expand = f.locator("#expand-all");
      if (await expand.count()) {
        await expand.click({ force: true });
        await page.waitForTimeout(1500);
        break;
      }
    }
  } catch (_) {
    /* tree iframe optional */
  }
  await shot(page, "09-audit-tree-expanded");

  await page.waitForTimeout(1000);
  await context.close();
  await browser.close();

  const videos = fs.readdirSync(RECORD).filter((f) => f.endsWith(".webm"));
  if (!videos.length) throw new Error("No video recorded");
  const src = path.join(RECORD, videos[0]);
  const destWebm = path.join(OUT, "walkthrough.webm");
  fs.copyFileSync(src, destWebm);
  console.log("video", destWebm);

  // Transcode to mp4 for GitHub README friendliness
  const { spawnSync } = require("child_process");
  const destMp4 = path.join(OUT, "walkthrough.mp4");
  const ff = spawnSync(
    "ffmpeg",
    ["-y", "-i", destWebm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", destMp4],
    { encoding: "utf8" },
  );
  if (ff.status !== 0) {
    console.error(ff.stderr);
    throw new Error("ffmpeg failed");
  }
  console.log("mp4", destMp4);
  console.log("done");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
