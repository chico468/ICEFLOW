import { expect, test } from '@playwright/test';
import { gotoApp, openScreen, trackErrors } from './helpers';

test('calculated alternatives update the chart and the selected profile sails unchanged', async ({ page }) => {
  test.setTimeout(240_000);
  const errors = trackErrors(page);
  await gotoApp(page);
  await openScreen(page, 'Plan');

  const alternativesResponse = page.waitForResponse(
    (response) => response.url().includes('/api/v1/route/alternatives')
      && response.request().method() === 'POST',
    { timeout: 210_000 },
  );
  await page.getByRole('button', { name: 'Plan voyage' }).click();
  const alternativeResult = await (await alternativesResponse).json();
  const candidates = alternativeResult.candidates as {
    id: string;
    is_feasible: boolean;
    weights: { fuel: number; time: number; risk: number };
    evaluation: { waypoints: { latitude: number; longitude: number }[] };
  }[];
  expect(candidates.length).toBeGreaterThan(1);

  const balanced = candidates.find((candidate) => candidate.id === 'balanced');
  const fastest = candidates.find((candidate) => candidate.id === 'fastest');
  expect(balanced?.is_feasible).toBe(true);
  expect(fastest?.is_feasible).toBe(true);
  const widgetRow = page.getByTestId('route-widget-row');
  await expect(widgetRow.getByTestId('route-candidate')).toHaveCount(candidates.length);
  const fastestWidget = page.getByTestId('route-candidate').filter({ has: page.getByRole('button', { name: 'Select Fastest route' }) });
  const expandFastest = page.getByRole('button', { name: 'Expand Fastest route details' });
  await expect(expandFastest).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByRole('button', { name: 'Select Fastest route' })).toHaveAttribute('aria-pressed', 'false');
  await expandFastest.click();
  await expect(page.getByRole('button', { name: 'Collapse Fastest route details' })).toHaveAttribute('aria-expanded', 'true');
  await expect(fastestWidget.getByText('Total distance')).toBeVisible();
  await expect(fastestWidget.getByText('Max compression')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Select Fastest route' })).toHaveAttribute('aria-pressed', 'false');
  await page.getByRole('button', { name: 'Collapse Fastest route details' }).click();
  await expect(page.getByRole('button', { name: 'Expand Fastest route details' })).toHaveAttribute('aria-expanded', 'false');

  await page.setViewportSize({ width: 700, height: 850 });
  const rowScroll = await widgetRow.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(rowScroll.scrollWidth).toBeGreaterThan(rowScroll.clientWidth);
  await page.setViewportSize({ width: 1280, height: 900 });

  const card = page.getByTestId('route-candidate').filter({ has: page.getByRole('button', { name: 'Select Fastest route' }) });
  const selectFastest = page.getByRole('button', { name: 'Select Fastest route' });
  await expect(selectFastest).toHaveAttribute('aria-pressed', 'false');
  const canvas = page.locator('[data-testid="map-cell"] canvas').first();
  const balancedFrame = await canvas.screenshot();
  await selectFastest.click();
  await expect(card).toHaveAttribute('aria-current', 'true');
  await expect(page.getByRole('button', { name: 'Select Fastest route' })).toHaveAttribute('aria-pressed', 'true');
  await page.waitForTimeout(250);
  const fastestFrame = await canvas.screenshot();
  expect(fastestFrame).not.toEqual(balancedFrame);

  await page.getByRole('button', { name: 'Continue to Sail' }).click();
  const voyageRequestPromise = page.waitForRequest(
    (request) => request.url().endsWith('/api/v1/voyage') && request.method() === 'POST',
    { timeout: 10_000 },
  );
  const voyageResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/voyage') && response.request().method() === 'POST',
    { timeout: 210_000 },
  );
  await page.getByRole('button', { name: /^Start Fastest voyage:/ }).click();
  const voyageRequest = await voyageRequestPromise;
  const voyageResponse = await voyageResponsePromise;
  const requestBody = voyageRequest.postDataJSON() as {
    route_profile_id: string;
    weights: { fuel: number; time: number; risk: number };
  };
  const voyage = await voyageResponse.json();

  expect(requestBody.route_profile_id).toBe('fastest');
  expect(requestBody.weights).toEqual(fastest?.weights);
  expect(voyage.route_profile_id).toBe('fastest');
  expect(voyage.plan_summary.weights).toEqual(fastest?.weights);
  expect(voyage.planned_route.map((point: { latitude: number; longitude: number }) => [
    point.latitude,
    point.longitude,
  ])).toEqual(fastest?.evaluation.waypoints.map((point) => [point.latitude, point.longitude]));
  await expect(page.getByText('UNDER WAY').first()).toBeVisible({ timeout: 60_000 });
  expect(errors).toEqual([]);
});
