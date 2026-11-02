#!/usr/bin/env node
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const failed = [];
page.on('requestfailed', (r) => failed.push(r.url() + ' :: ' + (r.failure()?.errorText || '')));
page.on('response', (r) => { if (r.status() === 404) failed.push('404 ' + r.url()); });

await page.goto('http://localhost:5199/', { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(2000);
console.log('FAILED/404:', JSON.stringify(failed.slice(0, 20), null, 1));

// nav through screens
const tabs = await page.$$('.flex.items-center.gap-1.rounded-lg'); // not reliable
// click each nav button by label
const labels = ['Plan', 'Sail', 'Voyage', '3D', 'Sea ice', 'Icebergs', 'Insights', 'Scorecard'];
const out = path.join(process.cwd(), 'e2e/evidence-screenshots');
fs.mkdirSync(out, { recursive: true });
for (const lab of labels) {
  const btn = await page.$(`nav button:has-text("${lab}")`);
  if (!btn) { console.log('no btn', lab); continue; }
  await btn.click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(out, `w0_screen_${lab.replace(/ /g, '_')}.png`) });
}
console.log('done');
await browser.close();