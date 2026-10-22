import { expect, test } from '@playwright/test';
import { canvasInk, gotoApp, openLayers, openScreen, trackErrors, visible } from './helpers';

test.use({ viewport: { width: 1366, height: 768 } });

const overlay = (page: import('@playwright/test').Page) => visible(page, '[data-testid="flow-overlay"]');
const toggle = (page: import('@playwright/test').Page, name: RegExp) => visible(page, '#map-layer-panel').getByRole('switch', { name });

async function enable(page: import('@playwright/test').Page, which: RegExp) {
  await openLayers(page);
  const t = toggle(page, which);
  if ((await t.getAttribute('aria-checked')) !== 'true') await t.click();
}

test('wind: the overlay appears, draws, and keeps moving', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await enable(page, /Wind \(simulated\)/);
  await expect(overlay(page)).toHaveCount(1);
  await expect.poll(async () => (await canvasInk(overlay(page))).ink, { timeout: 8000 }).toBeGreaterThan(50);
  const hashes = new Set<number>();
  for (let i = 0; i < 5; i += 1) {
    hashes.add((await canvasInk(overlay(page))).hash);
    await page.waitForTimeout(250);
  }
  expect(hashes.size, 'the picture must change over time').toBeGreaterThan(2);
  expect(errors).toEqual([]);
});

test('wind and current are independent layers: each can be on or off without affecting the other', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoApp(page);
  await openScreen(page, 'Sail');
  const legend = visible(page, '[aria-label="Chart legend"]');

  await enable(page, /Wind \(simulated\)/);
  await expect(overlay(page)).toHaveCount(1);
  await expect(legend).toContainText('Wind (simulated)');
  await expect(legend).not.toContainText('Current (simulated)');

  await toggle(page, /Ocean current \(simulated\)/).click();
  await expect(legend).toContainText('Wind (simulated)');
  await expect(legend).toContainText('Current (simulated)');

  // Turn wind off: the overlay must stay (current is still on) and must still be drawing.
  await toggle(page, /Wind \(simulated\)/).click();
  await expect(legend).not.toContainText('Wind (simulated)');
  await expect(legend).toContainText('Current (simulated)');
  await expect(overlay(page)).toHaveCount(1);
  await expect.poll(async () => (await canvasInk(overlay(page))).ink, { timeout: 8000 }).toBeGreaterThan(20);

  // Both off: nothing is rendered at all.
  await toggle(page, /Ocean current \(simulated\)/).click();
  await expect(overlay(page)).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('arrows mode draws a still, non-empty picture', async ({ page }) => {
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await enable(page, /Wind \(simulated\)/);
  await visible(page, '#map-layer-panel').getByRole('button', { name: 'Arrows' }).click();
  await expect.poll(async () => (await canvasInk(overlay(page))).ink, { timeout: 8000 }).toBeGreaterThan(50);
  const a = await canvasInk(overlay(page));
  await page.waitForTimeout(900);
  const b = await canvasInk(overlay(page));
  expect(b.hash).toBe(a.hash);
});

test('reduced motion: stated on screen, static vectors, not a frozen animation', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await enable(page, /Wind \(simulated\)/);
  await expect(visible(page, '[role="status"]').filter({ hasText: 'Reduced motion is on: showing static vectors' })).toHaveCount(1);
  await expect.poll(async () => (await canvasInk(overlay(page))).ink, { timeout: 8000 }).toBeGreaterThan(50);
  const a = await canvasInk(overlay(page));
  await page.waitForTimeout(900);
  expect((await canvasInk(overlay(page))).hash).toBe(a.hash);
});

test('a failed request shows an alert and draws nothing', async ({ page }) => {
  await page.route(/\/env\/field/, (r) => r.fulfill({ status: 500, body: 'boom' }));
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await enable(page, /Wind \(simulated\)/);
  await expect(visible(page, '[role="alert"]').filter({ hasText: /unavailable/i })).toHaveCount(1, { timeout: 15_000 });
  expect((await canvasInk(overlay(page))).ink).toBe(0);
});

test('a malformed response is handled: a notice, no crash', async ({ page }) => {
  const errors = trackErrors(page);
  await page.route(/\/env\/field/, (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await enable(page, /Wind \(simulated\)/);
  await expect(visible(page, '[role="status"]').filter({ hasText: /No wind or current data/ })).toHaveCount(1, { timeout: 15_000 });
  expect(errors).toEqual([]);
});

test('another screen\'s overlay never ghosts over this one: one visible overlay, hidden ones draw nothing, and it resumes on return', async ({ page }) => {
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await enable(page, /Wind \(simulated\)/);
  await expect.poll(async () => (await canvasInk(overlay(page))).ink, { timeout: 8000 }).toBeGreaterThan(50);

  // Layer toggles are global, so Plan's chart shows wind too once it is on screen. What must hold: exactly one
  // overlay is visible at a time, and every overlay on a hidden screen is idle and blank (not animating unseen).
  const hiddenInk = async (): Promise<number[]> => {
    const all = page.locator('[data-testid="flow-overlay"]');
    const out: number[] = [];
    for (let i = 0; i < (await all.count()); i += 1) {
      const one = all.nth(i);
      if (!(await one.isVisible())) out.push((await canvasInk(one)).ink);
    }
    return out;
  };
  await openScreen(page, 'Plan');
  await expect(overlay(page)).toHaveCount(1);
  await expect.poll(async () => (await hiddenInk()).every((n) => n === 0), { timeout: 5000 }).toBe(true);
  await expect.poll(async () => (await canvasInk(overlay(page))).ink, { timeout: 8000 }).toBeGreaterThan(50);

  await openScreen(page, 'Sail');
  await expect(overlay(page)).toHaveCount(1);
  await expect.poll(async () => (await canvasInk(overlay(page))).ink, { timeout: 8000 }).toBeGreaterThan(50);
  await expect.poll(async () => (await hiddenInk()).every((n) => n === 0), { timeout: 5000 }).toBe(true);
});

test('hiding the chart view stops its overlay: Regional view leaves the polar overlay idle and blank', async ({ page }) => {
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await enable(page, /Wind \(simulated\)/);
  await expect.poll(async () => (await canvasInk(overlay(page))).ink, { timeout: 8000 }).toBeGreaterThan(50);
  await page.keyboard.press('Escape');
  await visible(page, '[aria-label="Chart view"]').getByRole('button', { name: 'Regional' }).click();
  await expect(overlay(page)).toHaveCount(0); // the polar chart (and its overlay) is hidden
  const all = page.locator('[data-testid="flow-overlay"]');
  for (let i = 0; i < (await all.count()); i += 1) expect((await canvasInk(all.nth(i))).ink, `overlay ${i} must be blank`).toBe(0);
  await visible(page, '[aria-label="Chart view"]').getByRole('button', { name: 'Polar' }).click();
  await expect.poll(async () => (await canvasInk(overlay(page))).ink, { timeout: 8000 }).toBeGreaterThan(50);
});

test('stays stable through repeated zooming and panning', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await enable(page, /Wind \(simulated\)/);
  await toggle(page, /Ocean current \(simulated\)/).click();
  await page.keyboard.press('Escape');
  const cell = visible(page, '[data-testid="map-cell"] canvas').first();
  const b = (await cell.boundingBox())!;
  for (let i = 0; i < 8; i += 1) {
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
    await page.mouse.wheel(0, i % 2 ? 400 : -400);
    await page.mouse.down();
    await page.mouse.move(b.x + b.width / 2 + 80, b.y + b.height / 2 + 40, { steps: 4 });
    await page.mouse.up();
    await page.waitForTimeout(120);
  }
  expect(errors).toEqual([]);
  await expect(overlay(page)).toHaveCount(1);
});
