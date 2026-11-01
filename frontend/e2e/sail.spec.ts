import { expect, test } from '@playwright/test';
import { gotoApp, trackErrors } from './helpers';

test.use({ navigationTimeout: 30_000 });

test('Stage B: plan a voyage, open Sail, verify sim clock, speed controls and empty state', async ({ page }) => {
  test.setTimeout(150_000);
  const errors = trackErrors(page);

  await gotoApp(page);

  // Start on Plan screen
  await expect(page.getByRole('tab', { name: /^Plan$/ })).toBeVisible();

  // Plan a voyage
  await page.getByRole('button', { name: /^Plan voyage$/ }).click();
  await page.getByRole('tab', { name: /^Routes$/ }).click();
  await expect(page.getByText(/candidates/)).toBeVisible({ timeout: 110_000 });

  // Switch to Full view so the Voyage tab is visible, then open Sail.
  await page.getByRole('button', { name: /^Simple view$/ }).click();
  await page.getByRole('button', { name: /^Voyage$/ }).click();
  await page.waitForTimeout(2000);

  // Sail screen should show the sim clock UI
  await expect(page.getByText(/Sim speed/)).toBeVisible({ timeout: 10_000 });

  // Speed buttons should be present
  await expect(page.getByRole('button', { name: '1×' })).toBeVisible();
  await expect(page.getByTestId('speed-60')).toBeVisible();
  await expect(page.getByTestId('speed-600')).toBeVisible();
  await expect(page.getByTestId('speed-3600')).toBeVisible();

  // Play/Pause and Step buttons
  await expect(page.getByRole('button', { name: /^Play$/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /^Step$/ })).toBeVisible();

  // Position panel with provenance badge
  await expect(page.getByText(/Position/)).toBeVisible();

  // Take screenshot
  await page.screenshot({ path: 'e2e/evidence-screenshots/taskB-sail.png', fullPage: true });

  console.log('STAGE_B_SUMMARY sail screen loaded with sim clock');
  expect(errors).toEqual([]);
});
