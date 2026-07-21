import next from "eslint-config-next";

/**
 * Dependency boundaries (design D2):
 *   app → features → components / lib
 * - `components/` and `lib/` never import from `app/` or `features/`.
 * - a feature never imports another feature's internals (only its public
 *   `@/features/<name>` entry point; internal imports stay relative).
 * - `app/` composes downstream layers freely.
 */
const eslintConfig = [
  {
    ignores: [".next/**", "next-env.d.ts", "node_modules/**", "coverage/**"],
  },
  ...next,
  {
    files: ["components/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/app", "@/app/**", "@/features", "@/features/**"],
              message:
                "components/ and lib/ are shared layers: they must not import from app/ or features/ (design D2).",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["features/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/app", "@/app/**"],
              message:
                "features/ must not import from app/; app composes features, not the other way around (design D2).",
            },
            {
              group: ["@/features/*/**"],
              message:
                "A feature must not reach into another feature's internals; import its public @/features/<name> entry point only, and use relative paths within your own feature (design D2).",
            },
          ],
        },
      ],
    },
  },
  {
    // Tests are not production code: they may cross layer boundaries to exercise
    // the modules they cover. The boundary rules above apply to shipped code.
    files: ["**/*.test.{ts,tsx}", "test/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": "off",
    },
  },
];

export default eslintConfig;
