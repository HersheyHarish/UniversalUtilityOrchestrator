import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const orchestratorTarget =
    env.VITE_ORCHESTRATOR_URL ||
    process.env.VITE_ORCHESTRATOR_URL ||
    "http://localhost:7071";
  const apiProxy = {
    "/api": {
      target: orchestratorTarget,
      changeOrigin: true,
      secure: false,
    },
  };
  return {
    plugins: [react()],
    server: {
      port: 3000,
      host: true, // bind 0.0.0.0 so Docker can expose it
      proxy: apiProxy,
    },
    // `vite preview` does not inherit server.proxy unless mirrored here
    preview: {
      port: 3000,
      host: true,
      proxy: apiProxy,
    },
    build: {
      outDir: "dist",
      sourcemap: false,
    },
    test: {
      globals: true,
      environment: "jsdom",
      setupFiles: "./src/setupTests.js",
    },
  };
});
