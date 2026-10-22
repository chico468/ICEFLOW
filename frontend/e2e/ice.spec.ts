import { expect, test } from '@playwright/test';
import { gotoApp, openLayers, openScreen, visible } from './helpers';

test.use({ viewport: { width: 1366, height: 768 } });

const expandLegend = (page: import('@playwright/test').Page) => visible(page, '[aria-label="Chart legend"] button').first().click();

test('the collapsed legend is one line and says what is shown and whether it is simulated', async ({ page }) => {
  await gotoApp(page);
  await openScreen(page, 'Sail');
  const legend = visible(page, '[aria-label="Chart legend"]');
  await expect(legend).toContainText(/Ice concentration/);
  await expect(legend).toContainText(/simulated/i);
  expect((await legend.boundingBox())!.height).toBeLessThan(80);
});

test('expanded legend shows units, the five classes and the grid-cell size', async ({ page }) => {
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await expandLegend(page);
  const legend = visible(page, '[aria-label="Chart legend"]');
  for (const t of [/percent of each cell covered by ice/, /Open water/, /Very dense/, /Grid cell/, /SIMULATED/]) await expect(legend).toContainText(t);
});

test('change mode at +0 h says nothing is drawn instead of showing a scale', async ({ page }) => {
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await openLayers(page);
  await visible(page, '#map-layer-panel').getByRole('button', { name: 'Change' }).click({ force: true }); // aria-disabled: Playwright will not click it, but a user can, and gets the explanation
  await expandLegend(page);
  await expect(visible(page, '[aria-label="Chart legend"]')).toContainText(/after \+0 h/);
  await expect(visible(page, '[aria-label="Chart legend"]')).toContainText(/Nothing is drawn for this mode/);
});

test('thickness is not offered as drawn when the field carries no thickness', async ({ page }) => {
  await page.route(/\/ice\/field/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    delete body.thickness_m;
    await route.fulfill({ response: res, json: body });
  });
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await openLayers(page);
  await visible(page, '#map-layer-panel').getByRole('button', { name: 'Thickness' }).click({ force: true });
  await expandLegend(page);
  await expect(visible(page, '[aria-label="Chart legend"]')).toContainText(/no thickness data/);
});

test('a failed ice request is reported, and a blank chart is not called open water', async ({ page }) => {
  await page.route(/\/ice\/field/, (r) => r.fulfill({ status: 500, body: 'boom' }));
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await expandLegend(page);
  await expect(visible(page, '[aria-label="Chart legend"]')).toContainText(/NOT open water/, { timeout: 20_000 });
});

test('the observed-berg layer is labelled stale and not used for routing', async ({ page }) => {
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await expandLegend(page);
  const legend = visible(page, '[aria-label="Chart legend"]');
  await expect(legend).toContainText(/Observed snapshot \(USNIC-format\)/);
  await expect(legend).toContainText(/STALE/);
  await expect(legend).toContainText(/not used by the route planner/);
});

test('a missing cell is reported as "no data", separately from zero ice', async ({ page }) => {
  await page.route(/\/ice\/field/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.concentration[0][0] = null;
    body.concentration[1][1] = null;
    await route.fulfill({ response: res, json: body });
  });
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await expandLegend(page);
  await expect(visible(page, '[aria-label="Chart legend"]')).toContainText(/No data: 2 of [\d,]+ cells/);
  await expect(visible(page, '[aria-label="Chart legend"]')).toContainText(/Not zero ice/);
});

test('a malformed ice response is explained and does not crash the page', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route(/\/ice\/field/, (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await expandLegend(page);
  await expect(visible(page, '[aria-label="Chart legend"]')).toContainText(/malformed/i, { timeout: 20_000 });
  await expect(visible(page, '[aria-label="Chart legend"]')).toContainText(/not clear water/);
  expect(errors).toEqual([]);
});

test('a malformed wind/current response is explained in the legend and does not crash the page', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route(/\/env\/field/, (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await openLayers(page);
  await visible(page, '#map-layer-panel').getByRole('switch', { name: /Wind \(simulated\)/ }).click();
  await page.keyboard.press('Escape');
  await expandLegend(page);
  await expect(visible(page, '[aria-label="Chart legend"]')).toContainText(/response is malformed/i, { timeout: 20_000 });
  expect(errors).toEqual([]);
});

test('the layer panel disables nothing silently: an unavailable mode explains itself on hover text and in the legend', async ({ page }) => {
  await gotoApp(page);
  await openScreen(page, 'Sail');
  await openLayers(page);
  const change = visible(page, '#map-layer-panel').getByRole('button', { name: 'Change' });
  await expect(change).toHaveAttribute('aria-disabled', 'true');
  await expect(change).toHaveAttribute('title', /after \+0 h/);
});
