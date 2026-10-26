/**
 * Browser tests for the layout, the regional map and the flow layers.
 *
 * Setup (once; this also records @playwright/test in package.json AND package-lock.json, which is why it is
 * not pre-written there: the Dockerfile builds with `npm ci`, which needs the two to agree):
 *
 *   cd frontend
 *   npm i -D @playwright/test
 *   npx playwright install chromium
 *
 * Run:   npm run test:e2e          (starts the backend and the dev server if they are not already running)
 *        npm run test:e2e:ui       (interactive runner)
 *
 * The backend command can be overridden:  PYTHON=/path/to/python npm run test:e2e
 */
import { defineConfig, devices } from '@playwright/test';

const PYTHON = process.env.PYTHON ?? 'python';

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `${PYTHON} -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000`,
      cwd: '..',
      url: 'http://127.0.0.1:8000/api/v1/health',
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --port 5173 --strictPort',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
