import { defineConfig } from "vitest/config";

export default defineConfig({
  // passWithNoTests defaults to false; set it explicitly so a future config edit cannot silently
  // flip zero-test runs green. The node stack shipped without a vitest config, so this file exists
  // to make the guarantee committed rather than an accident of the default. (design Item 2)
  test: { passWithNoTests: false },
});
