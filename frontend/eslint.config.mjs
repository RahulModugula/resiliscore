import { FlatCompat } from "@eslint/eslintrc";
import { fileURLToPath } from "node:url";
import path from "node:path";

const compat = new FlatCompat({ baseDirectory: path.dirname(fileURLToPath(import.meta.url)) });
export default [
  { ignores: [".next/**", "out/**", "node_modules/**", "next-env.d.ts", "playwright-report/**", "test-results/**"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];
