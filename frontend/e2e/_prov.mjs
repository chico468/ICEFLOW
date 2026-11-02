import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const p = await b.newPage();
await p.goto('http://localhost:5199/', { waitUntil: 'networkidle' });
await p.waitForTimeout(1200);
await p.click('button.rounded-full'); await p.waitForTimeout(600);
for (const label of ['Plan','Sail','Voyage','3D','Sea ice','Icebergs','Insights','Scorecard']) {
  await p.evaluate((lbl)=>{const b=Array.from(document.querySelectorAll('nav button')).find(x=>(x.textContent||'').trim()===lbl); if(b)b.click();}, label);
  await p.waitForTimeout(1200);
  const txt = await p.evaluate(() => Array.from(document.querySelectorAll('[class*="prov"], [class*="badge"], [class*="simul"], [class*="no-data"], [class*="not-avail"], [class*="warn"]')).slice(0,6).map(e=>(e.textContent||'').trim().slice(0,90)).filter(Boolean));
  console.log('### '+label);
  console.log(JSON.stringify(txt, null, 1));
}
await b.close();
