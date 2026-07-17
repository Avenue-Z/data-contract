import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// eslint-config-next does not ship a native flat config, so it is bridged through FlatCompat.
// This mirrors what `create-next-app` generates — do not "modernise" it away without first
// checking that eslint-config-next has actually gained flat-config support.
const compat = new FlatCompat({ baseDirectory: __dirname });

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  { ignores: [".next/", "node_modules/"] },
];

export default eslintConfig;
