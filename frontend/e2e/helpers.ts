import { expect, type Locator, type Page } from '@playwright/test';

export const VIEWPORTS = [
  { width: 1024, height: 640 },
  { width: 1280, height: 720 },
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
] as const;

export interface Box { x: number; y: number; width: number; height: number }

export async function box(l: Locator): Promise<Box> {
  const b = await l.boundingBox();
  if (!b) throw new Error(`not visible: ${l}`);
  return b;
}

export const intersects = (a: Box, b: Box): boolean =>
  a.x < b.x + b.width - 0.5 && a.x + a.width > b.x + 0.5 && a.y < b.y + b.height - 0.5 && a.y + a.height > b.y + 0.5;

export const inside = (inner: Box, outer: Box, tol = 1): boolean =>
  inner.x >= outer.x - tol && inner.y >= outer.y - tol && inner.x + inner.width <= outer.x + outer.width + tol && inner.y + inner.height <= outer.y + outer.height + tol;

/** Only elements a user can actually see: Playwright's :visible excludes visibility:hidden and zero-size. */
export const visible = (page: Page, selector: string): Locator => page.locator(`${selector}:visible`);

export async function gotoApp(page: Page): Promise<void> {
  await page.goto('/');
  await expect(visible(page, '[data-testid="map-cell"]')).toHaveCount(1);
  // Let the first round of requests (stations, ice, bergs) finish, so the map's opening extent is the final one.
  await page.waitForLoadState('networkidle').catch(() => undefined);
}

export async function openScreen(page: Page, name: 'Plan' | 'Sail'): Promise<void> {
  await page.getByRole('button', { name: new RegExp(`^${name}`, 'i') }).first().click();
  await expect(visible(page, '[data-testid="map-cell"]')).toHaveCount(1);
}

export async function openLayers(page: Page): Promise<void> {
  const btn = visible(page, '[aria-label="Layers and legend settings"]');
  if ((await btn.getAttribute('aria-expanded')) !== 'true') await btn.click();
  await expect(visible(page, '#map-layer-panel')).toHaveCount(1);
}

/** Collect uncaught page errors so a crash fails the test instead of passing silently. */
export function trackErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  return errors;
}

/** Count non-transparent pixels in a canvas, and a cheap content hash. */
export async function canvasInk(l: Locator): Promise<{ ink: number; hash: number }> {
  return l.evaluate((el) => {
    const c = el as HTMLCanvasElement;
    const ctx = c.getContext('2d');
    if (!ctx || c.width === 0 || c.height === 0) return { ink: 0, hash: 0 };
    const d = ctx.getImageData(0, 0, c.width, c.height).data;
    let ink = 0;
    let hash = 0;
    for (let i = 3; i < d.length; i += 4) {
      if (d[i] > 0) {
        ink += 1;
        hash = (hash * 31 + (i >> 2) + d[i]) | 0;
      }
    }
    return { ink, hash };
  });
}

/** Parse the readout's "59° 43.5' S   064° 21.9' E" into signed decimal degrees. */
export function parseReadout(text: string): { lat: number; lon: number } {
  const m = [...text.matchAll(/(\d+)°\s*([\d.]+)'\s*([NSEW])/g)];
  if (m.length < 2) throw new Error(`cannot parse readout: ${text}`);
  const val = (x: RegExpMatchArray): number => (Number(x[1]) + Number(x[2]) / 60) * (x[3] === 'S' || x[3] === 'W' ? -1 : 1);
  return { lat: val(m[0]), lon: val(m[1]) };
}

/**
 * Wait until an attribute has stopped changing for `quietMs`. The regional map opens on the whole region and
 * re-fits to the route endpoints when the station list arrives, so "the initial extent" is only well defined
 * once it has settled.
 */
export async function settled(l: Locator, attr = 'data-zoom', quietMs = 1000): Promise<void> {
  let last: string | null = null;
  let since = Date.now();
  await expect
    .poll(
      async () => {
        const v = await l.getAttribute(attr);
        if (v !== last) {
          last = v;
          since = Date.now();
        }
        return Date.now() - since >= quietMs;
      },
      { timeout: 20_000 },
    )
    .toBe(true);
}
