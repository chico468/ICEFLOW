import { expect, test } from '@playwright/test';
import { box, canvasInk, gotoApp, openScreen, parseReadout, settled, trackErrors, visible } from './helpers';

test.use({ viewport: { width: 1366, height: 768 } });

async function openRegional(page: import('@playwright/test').Page) {
  await gotoApp(page);
  await openScreen(page, 'Plan');
  await visible(page, '[aria-label="Chart view"]').getByRole('button', { name: 'Regional' }).click();
  const host = visible(page, '[aria-label="Regional context map"]');
  await expect(host).toHaveCount(1);
  await expect.poll(async () => host.getAttribute('data-zoom')).not.toBeNull();
  await settled(host); // the opening extent re-fits when the station list arrives
  const canvas = host.locator('canvas');
  return { host, canvas };
}

const zoomOf = async (host: import('@playwright/test').Locator) => parseFloat((await host.getAttribute('data-zoom')) ?? 'NaN');
const centreOf = async (host: import('@playwright/test').Locator) => (await host.getAttribute('data-centre') ?? '').split(',').map(Number);

test('opens on a route-focused extent, not the whole region, and draws something', async ({ page }) => {
  const errors = trackErrors(page);
  const { host, canvas } = await openRegional(page);
  expect(await zoomOf(host)).toBeGreaterThan(1.3);
  expect((await canvasInk(canvas)).ink).toBeGreaterThan(1000);
  expect(errors).toEqual([]);
});

test('wheel zoom is anchored on the pointer', async ({ page }) => {
  const { host, canvas } = await openRegional(page);
  const b = await box(canvas);
  const px = b.x + b.width * 0.7;
  const py = b.y + b.height * 0.4;
  await page.mouse.move(px, py);
  const before = parseReadout((await visible(page, '[data-testid="regional-readout"]').textContent()) ?? '');
  const z0 = await zoomOf(host);
  await page.mouse.wheel(0, -500);
  await expect.poll(() => zoomOf(host)).toBeGreaterThan(z0 * 1.2);
  await page.mouse.move(px + 1, py);
  await page.mouse.move(px, py);
  const after = parseReadout((await visible(page, '[data-testid="regional-readout"]').textContent()) ?? '');
  expect(Math.abs(after.lat - before.lat)).toBeLessThan(0.6);
  expect(Math.abs(after.lon - before.lon)).toBeLessThan(0.6);
  expect(await page.evaluate(() => window.scrollY), 'the page must not scroll').toBe(0);
});

test('pinch (ctrl + wheel) zooms the map, not the page', async ({ page }) => {
  const { host, canvas } = await openRegional(page);
  const b = await box(canvas);
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
  const z0 = await zoomOf(host);
  await page.keyboard.down('Control');
  await page.mouse.wheel(0, -300);
  await page.keyboard.up('Control');
  await expect.poll(() => zoomOf(host)).toBeGreaterThan(z0);
});

test('drag pans, and the geography under a fixed screen point changes', async ({ page }) => {
  const { host, canvas } = await openRegional(page);
  const b = await box(canvas);
  const z = await zoomOf(host);
  // Zoom in first so there is room to pan.
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
  await page.mouse.wheel(0, -600);
  await expect.poll(() => zoomOf(host)).toBeGreaterThan(z);
  const c0 = await centreOf(host);
  await page.mouse.move(b.x + 300, b.y + 300);
  await page.mouse.down();
  await page.mouse.move(b.x + 420, b.y + 360, { steps: 6 });
  await page.mouse.up();
  await expect.poll(async () => (await centreOf(host)).join()).not.toBe(c0.join());
});

test('double-click zooms in', async ({ page }) => {
  const { host, canvas } = await openRegional(page);
  const b = await box(canvas);
  const z0 = await zoomOf(host);
  await page.mouse.dblclick(b.x + b.width / 2, b.y + b.height / 2);
  await expect.poll(() => zoomOf(host)).toBeGreaterThan(z0 * 1.7);
});

test('buttons: zoom in, zoom out, reset to the route extent, and show the whole region', async ({ page }) => {
  const { host } = await openRegional(page);
  const z0 = await zoomOf(host);
  const c0 = await centreOf(host);
  const tb = visible(page, '[aria-label="Map controls"]');
  await tb.getByRole('button', { name: 'Zoom in' }).click();
  await expect.poll(() => zoomOf(host)).toBeGreaterThan(z0 * 1.3);
  await tb.getByRole('button', { name: 'Zoom out' }).click();
  await tb.getByRole('button', { name: 'Zoom out' }).click();
  await expect.poll(() => zoomOf(host)).toBeLessThan(z0);
  await tb.getByRole('button', { name: 'Reset to the route extent' }).click();
  await expect.poll(async () => Math.abs((await zoomOf(host)) - z0)).toBeLessThan(0.02);
  expect(Math.abs((await centreOf(host))[0] - c0[0])).toBeLessThan(0.2);
  await tb.getByRole('button', { name: 'Show the whole region' }).click();
  await expect.poll(() => zoomOf(host)).toBeLessThan(1.02);
});

test('keyboard: arrows pan, + and - zoom, 0 resets; keys inside a control are not stolen', async ({ page }) => {
  const { host, canvas } = await openRegional(page);
  const z0 = await zoomOf(host);
  const c0 = await centreOf(host);
  void c0;
  const b = await box(canvas);
  await page.mouse.click(b.x + b.width / 2, b.y + b.height / 2); // focuses the map
  await expect(host).toBeFocused();
  await page.keyboard.press('+');
  await expect.poll(() => zoomOf(host)).toBeGreaterThan(z0 * 1.3);
  // Zoom in far enough that the view is narrower than the region; only then can it pan sideways (when the whole
  // region already fits across the map, horizontal pan is correctly locked).
  await page.keyboard.press('+');
  await page.keyboard.press('+');
  await expect.poll(() => zoomOf(host)).toBeGreaterThan(z0 * 3);
  const c1 = await centreOf(host);
  await page.keyboard.press('ArrowRight');
  await expect.poll(async () => (await centreOf(host))[0]).toBeGreaterThan(c1[0] + 0.5);
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('ArrowDown');
  await expect.poll(async () => (await centreOf(host))[1]).toBeLessThan(c1[1] - 0.2);
  await page.keyboard.press('0');
  await expect.poll(async () => Math.abs((await zoomOf(host)) - z0)).toBeLessThan(0.02);

  // Focus a toolbar button: "+" must not zoom the map.
  await visible(page, '[aria-label="Map controls"]').getByRole('button', { name: 'Zoom out' }).focus();
  const before = await zoomOf(host);
  await page.keyboard.press('+');
  await page.waitForTimeout(400);
  expect(await zoomOf(host)).toBeCloseTo(before, 3);
});

test('with reduced motion, zoom jumps instead of easing', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const { host } = await openRegional(page);
  const z0 = await zoomOf(host);
  await visible(page, '[aria-label="Map controls"]').getByRole('button', { name: 'Zoom in' }).click();
  await expect.poll(() => zoomOf(host), { timeout: 400 }).toBeGreaterThan(z0 * 1.4);
});

test('the polar and regional views are independent: switching back leaves the polar chart as it was', async ({ page }) => {
  const { host } = await openRegional(page);
  await visible(page, '[aria-label="Map controls"]').getByRole('button', { name: 'Zoom in' }).click();
  await visible(page, '[aria-label="Chart view"]').getByRole('button', { name: 'Polar' }).click();
  await expect(visible(page, '[aria-label="Regional context map"]')).toHaveCount(0);
  await visible(page, '[aria-label="Chart view"]').getByRole('button', { name: 'Regional' }).click();
  expect(await zoomOf(host)).toBeGreaterThan(1.3); // the regional view kept its own zoom
});
