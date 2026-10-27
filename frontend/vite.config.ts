/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    // design/ (tokens, sprites) sits next to frontend/; in Docker it is mounted at /design.
    fs: { allow: [".", "../design"] },
    // Docker on Windows: bind mounts don't deliver file events, so poll (VITE_POLLING=true).
    watch: process.env.VITE_POLLING === "true" ? { usePolling: true, interval: 300 } : undefined,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
