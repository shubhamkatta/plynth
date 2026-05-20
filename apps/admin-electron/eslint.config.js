import tsPlugin from "@typescript-eslint/eslint-plugin";
import tsParser from "@typescript-eslint/parser";
import reactPlugin from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  {
    ignores: ["out/**", "dist/**", "node_modules/**"],
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 2022,
        sourceType: "module",
        ecmaFeatures: { jsx: true },
      },
      globals: {
        window:    "readonly",
        document:  "readonly",
        console:   "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        fetch:     "readonly",
        URL:       "readonly",
        process:   "readonly",
      },
    },
    plugins: {
      "@typescript-eslint": tsPlugin,
      "react":              reactPlugin,
      "react-hooks":        reactHooks,
    },
    settings: { react: { version: "detect" } },
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "@typescript-eslint/no-explicit-any": "off",
      "react/jsx-uses-react":      "off",
      "react/react-in-jsx-scope":  "off",
      "react/jsx-uses-vars":       "error",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps":"warn",
      "no-console":                ["warn", { allow: ["warn", "error"] }],
    },
  },
];
