import { expect, test } from '@playwright/test';
import { VIEWPORTS, box, gotoApp, inside, intersects, openLayers, openScreen, trackErrors, visible } from './helpers';

for (const vp of VIEWPORTS) {
  test.describe(`layout at ${vp.width}x${vp.height}`, () => {
    test.use({ viewport: vp });

    for (const screen of ['Plan', 'Sail'] as const) {
      test(`${screen}: the map keeps a usable size and nothing overlaps it`, async ({ page }) => {
        const errors = trackErrors(page);
        await gotoApp(page);
        await openScreen(page, screen);

        const cell = await box(visible(page, '[data-testid="map-cell"]'));
        expect(cell.height, 'map cell height').toBeGreaterThanOrEqual(298);
        expect(cell.width, 'map cell width').toBeGreaterThan(500);

        // The dock (when this screen has one) sits BELOW the map, never over it.
        const dock = visible(page, '[data-testid="dock"]');
        if ((await dock.count()) === 1) {
          const d = await box(dock);
          expect(intersects(cell, d), 'dock overlaps the map').toBe(false);
          expect(d.y).toBeGreaterThanOrEqual(cell.y + cell.height - 1);
        }

        // Exactly one control stack, one legend and one view switch are visible.
        await expect(visible(page, '[aria-label="Map controls"]')).toHaveCount(1);
        await expect(visible(page, '[aria-label="Chart legend"]')).toHaveCount(1);
        await expect(visible(page, '[aria-label="Chart view"]')).toHaveCount(1);

        // Overlays stay inside the map cell and do not collide with each other.
        const toolbar = await box(visible(page, '[aria-label="Map controls"]'));
        const legend = await box(visible(page, '[aria-label="Chart legend"]'));
        expect(inside(toolbar, cell), 'toolbar inside the map').toBe(true);
        expect(inside(legend, cell), 'legend inside the map').toBe(true);
        expect(intersects(toolbar, legend), 'toolbar overlaps legend').toBe(false);

        // The page itself never scrolls sideways, and nothing essential is cut off by the window.
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow).toBeLessThanOrEqual(0);
        expect(cell.x + cell.width).toBeLessThanOrEqual(vp.width + 1);
        expect(cell.y + cell.height).toBeLessThanOrEqual(vp.height + 1);
        expect(errors).toEqual([]);
      });

      test(`${screen}: the layer panel and an expanded legend stay inside the map, above the dock`, async ({ page }) => {
        await gotoApp(page);
        await openScreen(page, screen);
        await openLayers(page);
        const cell = await box(visible(page, '[data-testid="map-cell"]'));
        const panel = await box(visible(page, '#map-layer-panel'));
        expect(inside(panel, cell), 'layer panel inside the map cell').toBe(true);
        const dock = visible(page, '[data-testid="dock"]');
        if ((await dock.count()) === 1) expect(intersects(panel, await box(dock)), 'layer panel runs under the dock').toBe(false);

        // Expand the legend as well: it may be tall, but must be bounded by the map and scroll inside itself.
        await visible(page, '[aria-label="Chart legend"] button').first().click();
        const legend = await box(visible(page, '[aria-label="Chart legend"]'));
        expect(inside(legend, cell), 'expanded legend inside the map cell').toBe(true);
        expect(intersects(legend, panel), 'legend overlaps the layer panel').toBe(false);
      });
    }

    test('switching screens leaves no duplicate controls, legends or ghost text', async ({ page }) => {
      await gotoApp(page);
      for (const name of ['Sail', 'Plan', 'Sail', 'Plan'] as const) {
        await openScreen(page, name);
        await expect(visible(page, '[aria-label="Map controls"]')).toHaveCount(1);
        await expect(visible(page, '[aria-label="Chart legend"]')).toHaveCount(1);
        await expect(visible(page, '[aria-label="Chart view"]')).toHaveCount(1);
        await expect(visible(page, '[data-testid="map-cell"]')).toHaveCount(1);
      }
    });

    test('Sail dock: one panel at a time, tabs switch, badges stay visible', async ({ page }) => {
      await gotoApp(page);
      await openScreen(page, 'Sail');
      const tabs = visible(page, '[data-testid="dock"] [role="tab"]');
      await expect(tabs).toHaveCount(4);
      // One panel body at a time: never more than one tabpanel. (At the smallest window the dock may be collapsed to
      // its tab strip, in which case there is none; the tabs and their badges are still there.)
      expect(await visible(page, '[data-testid="dock"] [role="tabpanel"]').count()).toBeLessThanOrEqual(1);
      for (const name of ['Vessel', 'Voyage control', 'Alerts', 'X-band radar']) {
        await expect(tabs.filter({ hasText: name })).toHaveCount(1);
      }
      // Keyboard: arrow keys move between tabs.
      await tabs.first().focus();
      await page.keyboard.press('ArrowRight');
      await expect(tabs.nth(1)).toBeFocused();
    });
  });
}
