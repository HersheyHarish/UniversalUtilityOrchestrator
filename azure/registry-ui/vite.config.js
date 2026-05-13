import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const registryTarget =
    env.VITE_REGISTRY_URL ||
    process.env.VITE_REGISTRY_URL ||
    "http://localhost:7072";
  const apiProxy = {
    "/api": {
      target: registryTarget,
      changeOrigin: true,
      secure: false,
    },
  };

  return {
    plugins: [react()],
    server: {
      port: 3000,
      host: true,
      proxy: apiProxy,
    },
    preview: {
      port: 3000,
      host: true,
      proxy: apiProxy,
    },
    build: {
      outDir: "dist",
      sourcemap: false,
    },
  };
});
