import { defineConfig } from "@playwright/test";

const SESSION_TOKEN = "0".repeat(64);
const DEFAULT_PYTHON = process.platform === "win32"
  ? "..\\.venv\\Scripts\\python.exe"
  : "../.venv/bin/python";
const PYTHON = process.env.KERUI_E2E_PYTHON ?? DEFAULT_PYTHON;

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:1420",
    trace: "on-first-retry"
  },
  webServer: [
    {
      command: `"${PYTHON}" -m kerui_recruit.bench.e2e_sidecar --port 43127 --token ${SESSION_TOKEN} --data-root .e2e-data`,
      cwd: "../backend",
      url: "http://127.0.0.1:43127/health/ready",
      reuseExistingServer: false,
      timeout: 60_000
    },
    {
      command: "npm run dev",
      url: "http://localhost:1420",
      reuseExistingServer: true,
      timeout: 60_000
    }
  ]
});
