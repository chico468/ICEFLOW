import { expect, test } from '@playwright/test';
import { box, gotoApp, openScreen, parseReadout, settled, trackErrors, visible } from './helpers';

test.use({ viewport: { width: 1366, height: 768 } });

async function openRegional(page: import('@playwright/test').Page) {
  await gotoApp(page);
  const planButton = page.getByRole('button', { name: /^Plan/i }).first();
  if (await planButton.getAttribute('aria-pressed') !== 'true') {
    await openScreen(page, 'Plan');
  }
  await visible(page, '[aria-label="Chart view"]').getByRole('button', { name: 'Regional' }).click();
  const host = visible(page, '[aria-label="Regional context map"]');
  await expect(host).toHaveCount(1);
  await expect.poll(async () => host.getAttribute('data-zoom')).not.toBeNull();
  await expect(host).toHaveAttribute('data-map-ready', 'true', { timeout: 60_000 });
  await expect(host).toHaveAttribute('data-regional-route-endpoints-ready', 'true', { timeout: 30_000 });
  await settled(host); // the opening extent re-fits when the station list arrives
  const canvas = host.locator('.mapboxgl-canvas');
  return { host, canvas };
}

const zoomOf = async (host: import('@playwright/test').Locator) => parseFloat((await host.getAttribute('data-zoom')) ?? 'NaN');
const centreOf = async (host: import('@playwright/test').Locator) => (await host.getAttribute('data-centre') ?? '').split(',').map(Number);

test('opens on a route-focused extent, not the whole region, and draws something', async ({ page }) => {
  const errors = trackErrors(page);
  const { host, canvas } = await openRegional(page);
  expect(await zoomOf(host)).toBeGreaterThan(1.3);
  await expect(host).toHaveAttribute('data-map-ready', 'true');
  await expect(canvas).toBeVisible();
  const rendered = await canvas.evaluate((element) => {
    const mapCanvas = element as HTMLCanvasElement;
    return Boolean(mapCanvas.width > 0 && mapCanvas.height > 0 && (mapCanvas.getContext('webgl2') || mapCanvas.getContext('webgl')));
  });
  expect(rendered, 'Mapbox must initialize a non-empty WebGL canvas').toBe(true);
  const bounds = await box(canvas);
  expect(bounds.width).toBeGreaterThan(500);
  expect(bounds.height).toBeGreaterThan(250);
  expect(errors).toEqual([]);
});

test('regional iceberg markers use the same simulated and observed API catalogues', async ({ page }) => {
  const [simulatedResponse, observedResponse] = await Promise.all([
    page.request.get('http://127.0.0.1:8000/api/v1/icebergs?lead_hours=0'),
    page.request.get('http://127.0.0.1:8000/api/v1/icebergs/observed'),
  ]);
  const simulated = await simulatedResponse.json() as { count: number };
  const observed = await observedResponse.json() as { available: boolean; count: number };
  const { host } = await openRegional(page);
  await expect(host).toHaveAttribute('data-map-ready', 'true');
  await expect.poll(async () => Number(await host.getAttribute('data-regional-simulated-iceberg-count')))
    .toBe(simulated.count);
  await expect.poll(async () => Number(await host.getAttribute('data-regional-observed-iceberg-count')))
    .toBe(observed.available ? observed.count : 0);
  expect(simulated.count).toBeGreaterThan(0);
});

test('GFS wind particles load, animate on the WebGL map, and toggle without reloading it', async ({ page }) => {
  const errors = trackErrors(page);
  const relevantConsoleErrors: string[] = [];
  const gfsResponses: number[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error' && /webgl|raster-array|raster-particle|gfs-winds/i.test(message.text())) {
      relevantConsoleErrors.push(message.text());
    }
  });
  page.on('response', (response) => {
    if (response.url().includes('gfs-winds')) gfsResponses.push(response.status());
  });
  const { host } = await openRegional(page);
  await expect(host).toHaveAttribute('data-map-ready', 'true');
  await expect(host).toHaveAttribute('data-wind-layer-present', 'true');
  await expect(host).toHaveAttribute('data-wind-source-status', 'ready', { timeout: 60_000 });
  expect(gfsResponses).toContain(200);
  const cameraBeforeToggle = { zoom: await zoomOf(host), centre: await centreOf(host) };

  const canvas = host.locator('.mapboxgl-canvas');
  const controls = visible(page, '[aria-label="Map controls"]');
  const toggle = controls.getByRole('button', { name: 'Wind particles' });
  await expect(toggle).toHaveAttribute('title', /GFS atmospheric wind velocity/);
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');

  const frameBefore = await canvas.screenshot();
  await page.waitForTimeout(1200);
  const frameAfter = await canvas.screenshot();
  expect(frameAfter).not.toEqual(frameBefore);

  await toggle.click();
  await expect(host).toHaveAttribute('data-wind-layer-visibility', 'none');
  const hiddenFrame = await canvas.screenshot();
  await toggle.click();
  await expect(host).toHaveAttribute('data-wind-layer-visibility', 'visible');
  await page.waitForTimeout(1200);
  const restoredFrame = await canvas.screenshot();
  expect(restoredFrame).not.toEqual(hiddenFrame);
  expect(Math.abs((await zoomOf(host)) - cameraBeforeToggle.zoom)).toBeLessThan(0.02);
  const centreAfterToggle = await centreOf(host);
  expect(Math.abs(centreAfterToggle[0] - cameraBeforeToggle.centre[0])).toBeLessThan(0.02);
  expect(Math.abs(centreAfterToggle[1] - cameraBeforeToggle.centre[1])).toBeLessThan(0.02);
  expect(errors).toEqual([]);
  expect(relevantConsoleErrors).toEqual([]);
});

test('Copernicus ice-edge classes render transparently and label stale observations', async ({ page }) => {
  const tileRequests: string[] = [];
  const renderedTileResponses: Array<{ status: number; url: string }> = [];
  const renderedTileFailures: string[] = [];
  page.on('request', (request) => {
    if (/\/api\/v1\/environment\/layers\/tiles\/edge\//.test(request.url())) {
      tileRequests.push(request.url());
    }
  });
  page.on('response', (response) => {
    if (/\/api\/v1\/environment\/layers\/tiles\/edge\//.test(response.url())) {
      renderedTileResponses.push({ status: response.status(), url: response.url() });
    }
  });
  page.on('requestfailed', (request) => {
    if (/\/api\/v1\/environment\/layers\/tiles\/edge\//.test(request.url())) {
      renderedTileFailures.push(request.failure()?.errorText ?? 'unknown network failure');
    }
  });
  const { host } = await openRegional(page);
  await expect(host).toHaveAttribute('data-map-ready', 'true');
  await expect(page.getByText('Regional map unavailable', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Sea ice type' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Observed sea-ice edge' })).toBeVisible();
  const status = visible(page, '[data-testid="regional-sea-ice-status"]');
  await expect.poll(async () => status.getAttribute('data-status'), { timeout: 60_000 }).not.toBe('loading');

  const initialStatus = await status.getAttribute('data-status');
  expect(['ready', 'stale', 'unavailable', 'outside_coverage', 'unsupported_time', 'error']).toContain(initialStatus);
  const pairedTime = await host.getAttribute('data-regional-sea-ice-valid-time');
  const targetTime = await host.getAttribute('data-regional-sea-ice-target-time');
  if (pairedTime) await expect(status).toContainText(/observed \d{4}-\d{2}-\d{2}/);
  if (targetTime) {
    await expect(status).toContainText(/Workspace target \d{4}-\d{2}-\d{2}/);
    await expect(status).toContainText('SEAICE_GLO_SEAICE_L4_NRT_OBSERVATIONS_011_001');
  }
  console.info(`Regional sea-ice check: status=${initialStatus}; valid-time=${pairedTime ?? 'unavailable'}`);
  if (initialStatus === 'stale') await expect(status).toContainText('STALE OBSERVATION');
  if (initialStatus === 'outside_coverage') await expect(status).toContainText('Outside source coverage');
  if (initialStatus === 'unsupported_time') await expect(status).toContainText('Unsupported time');
  if (initialStatus === 'unavailable') await expect(status).toContainText('Unavailable');
  if (initialStatus === 'ready' || initialStatus === 'stale') {
    await expect.poll(() => renderedTileResponses.length, { timeout: 30_000 }).toBeGreaterThan(0);
    expect(
      renderedTileResponses.every(({ status: statusCode }) => statusCode === 200),
      JSON.stringify(renderedTileResponses),
    ).toBe(true);
    expect(renderedTileFailures).toEqual([]);
    expect(tileRequests.length).toBeGreaterThan(0);
    expect(tileRequests.every(
      (url) => url.includes(`source_valid_time_utc=${encodeURIComponent(pairedTime ?? '')}`),
    )).toBe(true);
    await expect(visible(page, '[data-testid="regional-sea-ice-edge-legend"]')).toBeVisible();

    const tileUrl = new URL(tileRequests[0]);
    const pixels = await page.evaluate(async (url) => {
      const response = await fetch(url);
      const bitmap = await createImageBitmap(await response.blob());
      const canvas = document.createElement('canvas');
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const context = canvas.getContext('2d');
      if (!context) throw new Error('Canvas 2D is unavailable for checking the rendered tile.');
      context.drawImage(bitmap, 0, 0);
      const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
      let transparent = 0;
      let opaque = 0;
      for (let index = 3; index < data.length; index += 4) {
        if (data[index] === 0) transparent += 1;
        if (data[index] === 255) opaque += 1;
      }
      bitmap.close();
      return { transparent, opaque };
    }, tileUrl.toString());
    expect(pixels.transparent, 'missing-data areas must stay transparent').toBeGreaterThan(0);
    expect(pixels.opaque, 'the source tile must contain observed ice classes').toBeGreaterThan(0);
  }

  const windToggle = visible(page, '[aria-label="Map controls"]').getByRole('button', { name: 'Wind particles' });
  if (await windToggle.getAttribute('aria-pressed') === 'true') {
    await windToggle.click();
    await expect(host).toHaveAttribute('data-wind-layer-visibility', 'none');
  }
  const mapCanvas = host.locator('.mapboxgl-canvas');
  if (await windToggle.getAttribute('aria-pressed') === 'false') {
    await windToggle.click();
    await expect(host).toHaveAttribute('data-wind-layer-visibility', 'visible');
  }
  expect(await mapCanvas.isVisible()).toBe(true);
});

test.skip('wheel zoom is anchored on the pointer', async ({ page }) => {
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
  await expect.poll(() => zoomOf(host), { timeout: 2_000 }).toBeGreaterThan(z0 * 1.4);
});

test('the polar and regional views are independent: switching back leaves the polar chart as it was', async ({ page }) => {
  const { host } = await openRegional(page);
  await visible(page, '[aria-label="Map controls"]').getByRole('button', { name: 'Zoom in' }).click();
  await visible(page, '[aria-label="Chart view"]').getByRole('button', { name: 'Polar' }).click();
  await expect(visible(page, '[aria-label="Regional context map"]')).toHaveCount(0);
  await visible(page, '[aria-label="Chart view"]').getByRole('button', { name: 'Regional' }).click();
  expect(await zoomOf(host)).toBeGreaterThan(1.3); // the regional view kept its own zoom
});
