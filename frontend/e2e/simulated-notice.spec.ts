import { test, expect } from '@playwright/test';

test('shows simulated notice after planning a route', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /plan/i }).first().click();
  await page.waitForTimeout(500);
  // Try to plan with defaults if possible
  const planButton = page.getByRole('button', { name: /plan route/i });
  if (await planButton.isVisible().catch(() => false)) {
    await planButton.click();
    await page.waitForTimeout(2000);
  }
  await expect(page.getByText('Planned on simulated ice and weather. Not for navigation.')).toBeVisible();
});
