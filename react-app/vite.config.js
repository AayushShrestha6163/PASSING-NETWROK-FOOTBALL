import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// This keeps talking to your existing api_server.py unchanged.
// In dev, /api requests are proxied to it; in prod, build the app with
// `npm run build` and serve the resulting dist/ folder from api_server.py
// (or drop dist/index.html + dist/assets into your current static folder).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
       "/api": "http://127.0.0.1:8000",
    },
  },
});
