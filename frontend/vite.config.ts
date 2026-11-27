import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      // tsdb service (service/tsdb): /tsdb/api/... -> http://localhost:8080/api/...
      "/tsdb": { target: "http://localhost:8080", changeOrigin: true, rewrite: (p) => p.replace(/^\/tsdb/, "") },
    },
  },
});
