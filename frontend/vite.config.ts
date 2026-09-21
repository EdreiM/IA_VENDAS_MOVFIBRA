import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      "/metrics": "http://127.0.0.1:8001",
      "/admin": "http://127.0.0.1:8001",
      "/chatwoot": "http://127.0.0.1:8001",
      "/health": "http://127.0.0.1:8001",
      "/chat": "http://127.0.0.1:8001",
      "/reset": "http://127.0.0.1:8001",
      "/media": "http://127.0.0.1:8001",
      "/webhooks": "http://127.0.0.1:8001",
    },
  },
});
