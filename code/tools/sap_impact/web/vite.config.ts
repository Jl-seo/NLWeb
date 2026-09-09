import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The app is served by the Python service under /app/ and its API sits at the
// origin root, so dev proxies every API path straight to a locally running
// service. Same URLs in dev and in production means no environment switch in
// the client.
const API_PATHS = ["/impact", "/ask", "/changes", "/review", "/dashboard", "/objects",
                   "/where-used", "/workspaces", "/agent", "/health", "/cards"];

export default defineConfig({
  base: "/app/",
  plugins: [react()],
  build: { outDir: "../service/webdist", emptyOutDir: true, sourcemap: false },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PATHS.map((path) => [path, { target: "http://localhost:8099", changeOrigin: true }]),
    ),
  },
});
