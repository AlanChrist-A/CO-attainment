import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  worker: { format: "es" },
  server: {
    port: 5173,
    fs: { allow: [".."] }, // the worker loads the Python files from ../backend/app
  },
});
