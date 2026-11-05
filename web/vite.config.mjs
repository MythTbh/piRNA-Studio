import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
export default defineConfig({
  base: "./",
  publicDir: false,
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    // Precomputed run fixtures, exports and benchmark pages already live here.
    emptyOutDir: false,
    lib: {
      entry: "src/index.ts",
      name: "PiRNAStudio",
      formats: ["iife"],
      fileName: () => "studio.js",
    },
    rollupOptions: {
      output: {
        assetFileNames: (asset) =>
          asset.name?.endsWith(".css") ? "studio.css" : "[name][extname]",
      },
    },
  },
  plugins: [
    {
      name: "offline-entry",
      async generateBundle() {
        this.emitFile({
          type: "asset",
          fileName: "index.html",
          source: await readFile(
            fileURLToPath(new URL("./index.html", import.meta.url)),
            "utf8",
          ),
        });
      },
    },
  ],
});
