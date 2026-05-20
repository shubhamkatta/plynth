import { resolve } from "node:path";
import { defineConfig, externalizeDepsPlugin } from "electron-vite";
import react from "@vitejs/plugin-react";

// electron-vite drives three Vite bundles in one config: main process,
// preload script, renderer. Each gets its own resolve aliases mirroring
// the tsconfig paths.

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    resolve: {
      alias: {
        "@main":    resolve("src/main"),
        "@shared":  resolve("src/shared"),
      },
    },
    build: {
      outDir: "out/main",
      lib: { entry: "src/main/index.ts" },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    resolve: {
      alias: {
        "@preload": resolve("src/preload"),
        "@shared":  resolve("src/shared"),
      },
    },
    build: {
      outDir: "out/preload",
      // Electron sandboxed preload (sandbox: true) requires CommonJS — ESM
      // preload is only supported when sandbox is disabled. Force `index.js`
      // output regardless of package.json `"type": "module"`.
      lib: {
        entry:    "src/preload/index.ts",
        formats:  ["cjs"],
        fileName: () => "index.js",
      },
    },
  },
  renderer: {
    root: "src/renderer",
    plugins: [react()],
    resolve: {
      alias: {
        "@renderer": resolve("src/renderer"),
        "@shared":   resolve("src/shared"),
      },
    },
    build: {
      outDir: resolve("out/renderer"),
      rollupOptions: {
        input: resolve("src/renderer/index.html"),
      },
    },
    server: {
      port: 5173,
    },
  },
});
