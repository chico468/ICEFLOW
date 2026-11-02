#!/usr/bin/env node
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT = path.join(process.cwd(), 'e2e/evidence-screenshots');
fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const errors = [];
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message));
page.on('requestfailed', (r) => errors.push('REQFAIL: ' + r.url() + ' ' + (r.failure()?.errorText || '')));

await page.goto('http://localhost:5199/', { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(2000);

const viewports = [
  { name: '1024x768', w: 1024, h: 768 },
  { name: '1280x720', w: 1280, h: 720 },
  { name: '1440x900', w: 1440, h: 900 },
  { name: '1920x1080', w: 1920, h: 1080 },
];
const report = [];
for (const vp of viewports) {
  await page.setViewportSize({ width: vp.w, height: vp.h });
  await page.waitForTimeout(800);
  const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
  const clientW = await page.evaluate(() => document.documentElement.clientWidth);
  const overflowEls = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('*').forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.right > window.innerWidth + 2) out.push({ tag: el.tagName, cls: String(el.className ?? '').slice(0, 60), right: Math.round(r.right) });
    });
    return out.slice(0, 10);
  });
  await page.screenshot({ path: path.join(OUT, `w0_${vp.name}_planner.png`), fullPage: false });
  report.push({ vp: vp.name, scrollW, clientW, overflow: scrollW > clientW, overflowEls, errors: errors.slice() });
}
console.log(JSON.stringify(report, null, 2));
console.log('CONSOLE_ERRORS:', JSON.stringify(errors.slice(0, 30)));
await browser.close();