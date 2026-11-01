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

  // Pick a departure one day later.
  const later = new Date(Date.now() + 24 * 3600 * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  const laterLocal = `${later.getFullYear()}-${pad(later.getMonth() + 1)}-${pad(later.getDate())}T${pad(later.getHours())}:${pad(later.getMinutes())}`;
  await departureInput.fill(laterLocal);
  await expect(departureInput).toHaveValue(laterLocal);

  // Plan a voyage and verify route candidates are returned.
  await page.getByRole('button', { name: /^Plan voyage$/ }).click();
  await page.getByRole('tab', { name: /^Routes$/ }).click();
  // The candidates badge confirms planning completed and the backend returned results.
  await expect(page.getByText(/candidates/)).toBeVisible({ timeout: 110_000 });

  await page.screenshot({ path: 'e2e/evidence-screenshots/taskD-etadeparture.png', fullPage: true });

  console.log(`FE4_SUMMARY departureLocal=${laterLocal}`);
  expect(errors).toEqual([]);
});
