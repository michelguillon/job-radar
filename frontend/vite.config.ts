import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// Dev server: proxy /api → the FastAPI container (compose service `api`), so the browser
// sees same-origin /api and there's no CORS in dev (job_radar_SPEC §10.4). The capability
// cookie (jr_write) is same-origin and rides along automatically.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    host: "0.0.0.0",
    port: 3000,
    // Dev tool on a trusted/local network (reached via localhost:8080 → mapped to :3000).
    // Relax Vite's DNS-rebinding host check. Prod serves the built bundle behind nginx.
    allowedHosts: true,
    proxy: {
      "/api": { target: "http://api:8000", changeOrigin: true },
    },
  },
});
