import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  base: "/modeio/dashboard/",
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
