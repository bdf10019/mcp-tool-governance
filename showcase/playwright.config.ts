import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4179",
    channel: "chrome",
    trace: "retain-on-failure"
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "mobile", use: { ...devices["Pixel 5"], viewport: { width: 390, height: 844 } } }
  ],
  webServer: {
    command: "pnpm preview",
    port: 4179,
    reuseExistingServer: true,
    timeout: 30_000
  }
});
