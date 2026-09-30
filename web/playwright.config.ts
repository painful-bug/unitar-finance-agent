import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1, // Shared backend settings make concurrent browser scenarios interfere.
  retries: process.env.CI ? 2 : 0,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      name: "deterministic MCP",
      command:
        "env MCP_HOST=127.0.0.1 MCP_PORT=8001 UV_CACHE_DIR=/tmp/finance-agent-playwright-uv-cache FINANCE_CHAT_STORE_PATH=/tmp/finance-agent-playwright-chats FINANCE_E2E_RESET_CHAT_STORE=1 uv run python tests/e2e_mcp_server.py",
      cwd: "..",
      port: 8001,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      name: "Vite",
      command:
        "env MCP_UPSTREAM=http://127.0.0.1:8001/mcp npm run dev -- --host 127.0.0.1 --port 4173",
      port: 4173,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
