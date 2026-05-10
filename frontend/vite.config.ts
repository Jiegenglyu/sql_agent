import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

function parsePort(value: string | undefined, fallback: number): number {
  const port = Number.parseInt(value ?? "", 10);
  return Number.isFinite(port) ? port : fallback;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");

  return {
    envDir: "..",
    plugins: [react()],
    server: {
      host: env.FRONTEND_HOST || "127.0.0.1",
      port: parsePort(env.FRONTEND_PORT, 5173)
    }
  };
});
