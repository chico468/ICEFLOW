import { expect, test } from '@playwright/test';
import { box, gotoApp, openScreen, trackErrors, visible } from './helpers';

const VIEWPORTS = [
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
] as const;

/** mapMinWidth from src/components/stageBudget.ts: max(520 px, 50 % of viewport). */
const minMapWidth = (w: number): number => Math.max(520, Math.floor(w * 0.5));

type View = 'Polar' | 'Regional';

async function switchToRegional(page: import('@playwright/test').Page): Promise<void> {
  await page.getByRole('group', { name: 'Chart view' }).getByRole('button', { name: 'Regional' }).click();
  const host = visible(page, '[aria-label="Regional context map"]');
  await expect(host).toHaveAttribute('data-map-ready', 'true', { timeout: 60_000 });
}

for (const vp of VIEWPORTS) {
  test.describe(`map minimum width at ${vp.width}x${vp.height}`, () => {
    test.use({ viewport: vp });

    test('map keeps its minimum width in Polar and Regional views, legend clears the controls', async ({
      page,
    }) => {
      const errors = trackErrors(page);
      await gotoApp(page);
      await openScreen(page, 'Plan');

      const cell = visible(page, '[data-testid="map-cell"]');
      const expected = minMapWidth(vp.width);

      // Polar is the initial view.
      const polar = await box(cell);
      expect(polar.width, 'Polar: map cell width').toBeGreaterThanOrEqual(expected);
      expect(polar.height, 'Polar: map cell height').toBeGreaterThanOrEqual(298);

      // The expanded legend must not reach the map controls.
      await visible(page, '[aria-label="Chart legend"] button').first().click();
      const toolbar = await box(visible(page, '[aria-label="Map controls"]'));
      const legend = await box(visible(page, '[aria-label="Chart legend"]'));
      expect(
        legend.x + legend.width,
        'Polar: legend must not reach the controls',
      ).toBeLessThanOrEqual(toolbar.x + 1);

      await page.screenshot({ path: `screenshots/map-size-${vp.width}x${vp.height}-polar.png`, fullPage: true });

      // Regional view.
      await switchToRegional(page);
      const regional = await box(cell);
      expect(regional.width, 'Regional: map cell width').toBeGreaterThanOrEqual(expected);
      expect(regional.height, 'Regional: map cell height').toBeGreaterThanOrEqual(298);

      await page.screenshot({ path: `screenshots/map-size-${vp.width}x${vp.height}-regional.png`, fullPage: true });

      expect(errors).toEqual([]);
    });
  });
}
