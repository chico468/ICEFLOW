import { expect, test } from '@playwright/test';
import { gotoApp, trackErrors } from './helpers';

test('FE-3: Scorecard screen renders from /api/v1/evidence/scorecard', async ({ page }) => {
  const errors = trackErrors(page);
  const consoleLogs: string[] = [];
  page.on('console', (msg) => consoleLogs.push(`${msg.type()}: ${msg.text()}`));

  await gotoApp(page);

  // Scorecard is an advanced screen: switch out of Simple view first.
  await page.getByRole('button', { name: /^Simple view$/ }).first().click();
  await page.getByRole('button', { name: /^Scorecard$/ }).click();

  // Wait for the Scorecard screen content (live endpoint or fixture fallback).
  await expect(page.getByText('Data source')).toBeVisible();
  await expect(page.locator('table tbody tr').first()).toBeVisible();

  await page.screenshot({ path: 'e2e/evidence-screenshots/taskC-scorecard.png', fullPage: true });

  console.log('FE3_CONSOLE_START');
  for (const line of consoleLogs) console.log(line);
  console.log('FE3_CONSOLE_END');

  const rowCount = await page.locator('table tbody tr').count();
  console.log(`FE3_SUMMARY rows=${rowCount}`);
  expect(rowCount).toBeGreaterThan(0);
  expect(errors).toEqual([]);
});
