import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = "http://localhost:8000";
export default defineConfig({
  plugins: [react()],
  server: { proxy: Object.fromEntries(["/invoices", "/reconciliations", "/contracts", "/billing", "/me", "/keys", "/audit"].map((p) => [p, api])) },
});
