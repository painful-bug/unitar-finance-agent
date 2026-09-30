import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const upstream = new URL(process.env.MCP_UPSTREAM ?? "http://127.0.0.1:8000/mcp");
const upstreamPath = upstream.pathname.replace(/\/$/, "");

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/mcp": {
        target: upstream.origin,
        changeOrigin: true,
        rewrite: (path) => `${upstreamPath}${path.slice("/mcp".length)}`,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
