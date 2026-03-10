import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const proxyTarget = process.env.MODEIO_DASHBOARD_PROXY_TARGET || "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react()],
  base: "/modeio/dashboard/",
  server: {
    host: "127.0.0.1",
    port: 4173,
    proxy: {
      "/healthz": proxyTarget,
      "/v1": proxyTarget,
      "/connectors": proxyTarget,
      "/modeio/api/v1": proxyTarget,
      "/modeio/admin/v1": proxyTarget,
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
  build: {
    outDir: path.resolve(__dirname, "../modeio_middleware/resources/dashboard"),
    emptyOutDir: true,
    assetsDir: "assets",
    rollupOptions: {
      output: {
        entryFileNames: "assets/dashboard.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: (assetInfo) => {
          const name = assetInfo.name ?? "asset";
          if (name.endsWith(".css")) {
            return "assets/dashboard.css";
          }
          const extension = path.extname(name);
          const baseName = path.basename(name, extension);
          return `assets/${baseName}${extension}`;
        },
      },
    },
  },
});
