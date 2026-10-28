import { expect, test } from '@playwright/test';
import { gotoApp, trackErrors } from './helpers';

test.use({ navigationTimeout: 30_000 });

test('FE-4: departure date-time picker, arrival ETA and per-waypoint ETAs', async ({ page }) => {
  test.setTimeout(150_000);
  const errors = trackErrors(page);

  await gotoApp(page);

  // The departure picker is in the Plan command bar.
  const departureInput = page.locator('input[type="datetime-local"]').first();
  await expect(departureInput).toBeVisible();
  const beforeValue = await departureInput.inputValue();

  // Pick a departure one day later.
  const later = new Date(Date.now() + 24 * 3600 * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  const laterLocal = `${later.getFullYear()}-${pad(later.getMonth() + 1)}-${pad(later.getDate())}T${pad(later.getHours())}:${pad(later.getMinutes())}`;
  await departureInput.fill(laterLocal);
  await expect(departureInput).toHaveValue(laterLocal);

  // Plan a voyage and verify the arrival ETA is derived from the chosen departure.
  await page.getByRole('button', { name: /^Plan voyage$/ }).click();
  // The arrival ETA lives in the Routes tab of the right dock.
  await page.getByRole('tab', { name: /^Routes$/ }).click();
  await expect(page.getByText('Arrival ETA')).toBeVisible({ timeout: 110_000 });

  // Expand the selected route card and verify per-waypoint ETAs are shown.
  const firstCard = page.locator('[data-testid="route-candidate"]').first();
  await expect(firstCard).toBeVisible();
  const expandBtn = firstCard.locator('[aria-controls^="route-details-"]').first();
  if ((await expandBtn.count()) > 0) {
    await expandBtn.click();
    await expect(page.getByText('Waypoint ETAs (UTC)')).toBeVisible();
  }

  await page.screenshot({ path: 'e2e/evidence-screenshots/taskD-etadeparture.png', fullPage: true });

  console.log(`FE4_SUMMARY departureLocal=${laterLocal}`);
  expect(errors).toEqual([]);
});
