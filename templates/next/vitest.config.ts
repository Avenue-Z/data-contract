import { defineConfig } from "vitest/config";

export default defineConfig({
  // passWithNoTests defaults to false; set it explicitly so a future config edit cannot silently
  // flip zero-test runs green. (design Item 2)
  test: { include: ["tests/**/*.test.ts"], passWithNoTests: false },
});
