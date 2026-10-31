import { test, expect } from '@playwright/test';
import { gotoApp } from './helpers';

test('shows simulated notice after planning a route', async ({ page }) => {
  await gotoApp(page);
  // The Mode select renders once endpoints have loaded; it is the last of the five selects.
  const modeSelect = page.locator('select:visible').last();
  await expect(modeSelect).toBeVisible({ timeout: 30_000 });
  await modeSelect.selectOption({ label: 'Simulated' });
  // Give React a moment to re-render with the new environment mode.
  await page.waitForTimeout(2000);
  // The hard SIMULATED banner appears when any simulated layer is on.
  await expect(page.getByText('Simulated ice and weather. Not for navigation.')).toBeVisible({ timeout: 15_000 });
});
