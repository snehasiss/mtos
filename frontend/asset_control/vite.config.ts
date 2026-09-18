import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/control-ui/",
  plugins: [react()],
  build: {
    outDir: "../../src/mtos/control_ui",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5302",
      "/health": "http://127.0.0.1:5302",
      "/static": "http://127.0.0.1:5302",
    },
  },
});
