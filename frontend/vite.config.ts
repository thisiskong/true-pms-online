import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      // tsdb service (service/tsdb) via the backend's read-only proxy, same path as in production.
      "/tsdb": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
