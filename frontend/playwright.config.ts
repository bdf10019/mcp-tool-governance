import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 45_000,
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:8132",
    browserName: "chromium",
    channel: "chrome",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "powershell -NoProfile -ExecutionPolicy Bypass -File ../scripts/run-e2e-server.ps1",
    cwd: ".",
    url: "http://127.0.0.1:8132/api/setup/status",
    timeout: 40_000,
    reuseExistingServer: false,
  },
});

