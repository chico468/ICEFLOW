#!/usr/bin/env node
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
const OUT = '/Users/venkateshs/Desktop/Photos/My Photo\'s/Kutty/python/ICEFLOW-frontend/frontend/e2e/evidence-screenshots';
fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const errors = [];
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message));
page.on('requestfailed', (r) => errors.push('REQFAIL: ' + r.url() + ' ' + (r.failure()?.errorText || '')));
await page.goto('http://localhost:5199/', { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(2000);
for (const vp of [{name:'1024x768',w:1024,h:768},{name:'1280x720',w:1280,h:720},{name:'1440x900',w:1440,h:900},{name:'1920x1080',w:1920,h:1080}]) {
  await page.setViewportSize({ width: vp.w, height: vp.h });
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(OUT, `w0_${vp.name}_planner.png`) });
}
console.log('SAVED 4 planner screenshots');
console.log('ERRORS:', JSON.stringify(errors.slice(0, 20)));
await browser.close();