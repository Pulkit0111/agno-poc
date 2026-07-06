import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";
import { configDefaults } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
});
