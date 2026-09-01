# Design System Tokens (Frontend)

## Purpose

The frontend exposes a brand-faithful design layer — color, typography, rhythm, radii and the user-facing theme switcher — that every screen and primitive consumes by token rather than by raw value. Two themes (light and dark) coexist; the active one is resolved server-side from a cookie, written into the first HTML, and overridable through a three-state control present on every shell. The layer enforces its own invariants via tests, so that the brand stays consistent and the contrast contract holds across future changes.

## Requirements

### Token layer and the two themes

- THE SYSTEM SHALL declare each colour token of the design export as a CSS custom property and expose it to Tailwind v4 via `@theme`, without reintroducing a `tailwind.config.{js,ts}` file (its absence is a `frontend-foundation` decision: `components.json` carries `"tailwind": {"config": ""}`).
- THE SYSTEM SHALL declare the same complete set of colour tokens in both themes: every token present in one theme is present in the other, with no omissions; the exact set and identity is asserted by `app/globals.tokens.test.ts`.
- WHERE no theme preference is persisted, THE SYSTEM SHALL apply the light theme by default and the dark theme when `prefers-color-scheme: dark`.
- WHEN the theme attribute is present on the root element, THE SYSTEM SHALL respect it in BOTH directions, overriding `prefers-color-scheme` — light on a dark system and dark on a light system alike — by ordering the three token-bearing blocks (light on `:root`, dark via media query, dark via attribute) so the attribute block wins on tie.
- THE SYSTEM SHALL make the colour of any surface, text or border depend on the resolved theme rather than directly on the media query; no consumer needs a `dark:` variant to express its colour.
- IF a background/text pair in either theme fails to meet the WCAG 2.2 AA contrast threshold (4.5:1 normal text, 3:1 large text and UI components), THEN THE SYSTEM SHALL correct it before delivery, and the measurement SHALL remain registered by `app/globals.contrast.test.ts`, which parses the three blocks and asserts every declared pair against the declared surface set.
- THE SYSTEM SHALL declare an explicit `color-scheme` on each theme so native controls, scrollbars and the browser chrome follow the resolved theme; the value accompanies the token block, not the media query alone.

### Three-state runtime control

- THE SYSTEM SHALL persist the user's preference in the non-sensitive cookie `autohostai.theme` with the values `light` and `dark`; the absence of the cookie is the third state («follow the system»), and no `"system"` value is ever persisted.
- WHEN serving a request, THE SYSTEM SHALL resolve the theme on the server and write the corresponding attribute on `<html>` from `app/layout.tsx`, alongside the `lang` attribute that already works this way, so the first paint is already the correct theme.
- THE SYSTEM SHALL NOT store the theme in Zustand or in any client store and SHALL NOT read it only on the client: client stores hydrate after the first paint, which would flash the wrong theme on every load.
- WHEN the user selects a theme, THE SYSTEM SHALL apply it immediately without reloading the page and SHALL write the cookie, with the mutation occurring in an effect and never during render.
- WHEN the user selects «follow the system», THE SYSTEM SHALL delete the cookie (with `max-age=0`) and remove the theme attribute from the root element together, so the next navigation honours the OS again.
- WHILE navigating between routes, THE SYSTEM SHALL preserve the resolved theme without flashing an incorrect one, because the attribute arrives in the HTML the server sends.

### Accessibility of the control

- THE SYSTEM SHALL offer the control as an accessible group with a translated name (`navigation.themeSwitcher.label`) and individual translated labels for each of the three choices (`navigation.themeSwitcher.{light,dark,system}`), present in both `locales/es` and `locales/en`.
- THE SYSTEM SHALL communicate the active preference via `aria-pressed` on each option, and SHALL keep a touch target of at least 44×44 px on every option, surviving any change to the underlying primitive via the `tap-target` utility.
- THE SYSTEM SHALL derive the preference that `aria-pressed` communicates from the `<html>` theme attribute — the same authority the server writes for the first paint — seeded at hydration by the server-resolved value, so that **any number of mounted instances** of the control agree after a change made in any one of them, without navigation, without a reload and without a client store. Per-instance state is not enough: the shell mounts this control twice below the `sm` breakpoint (the topbar's narrow layout, `frontend-foundation.md`), and an instance that never saw the click kept showing the button it was server-rendered with. Reading the attribute is not a second source of truth and is not «reading the theme only on the client», which the rule above forbids: the server snapshot returns the value resolved from the same cookie `app/layout.tsx` wrote the attribute from, so the two cannot disagree.
- THE SYSTEM SHALL communicate the choice to sighted users with an icon plus a translated tooltip, because an icon alone does not distinguish «light» from «system».

### Typography

- THE SYSTEM SHALL load Inter and JetBrains Mono through `next/font` (autohosted) and SHALL NOT load any font from `fonts.googleapis.com` or any other CDN at runtime; the files are fetched at build time and served from `/_next/static`.
- THE SYSTEM SHALL expose the two families as `@theme` tokens (sans and mono), each with a system fallback stack, so any Tailwind font utility resolves through the token.
- THE SYSTEM SHALL declare the ten typographic roles of the design export — `display-2xl`, `display-xl`, `display-lg-mobile`, `headline-lg`, `headline-md`, `body-lg`, `body-medium`, `body-base`, `data-mono`, `label-caps` — each as a `--text-<role>` token with its size, line height, letter spacing and weight; the built-in numeric scale (`text-sm`, `text-lg`, …) is preserved alongside.
- WHERE a metric or numeric datum is presented, THE SYSTEM SHALL have the monospace role (`data-mono`) available as a token; the application of the role to specific screens is owned by their own changes.

### Rhythm and radii

- THE SYSTEM SHALL declare in `@theme` the 4 px base spacing unit of the design export's rhythm and its named steps for gutter and margins (`--spacing-{gutter,margin-mobile,margin-desktop}`); the built-in numeric Tailwind scale on the same 4 px base already covers the rest and SHALL NOT be redeclared, because declaring numeric `--spacing-*` tokens collides with Tailwind v4's `max-w-*` resolution and breaks the layout.
- THE SYSTEM SHALL declare the radius scale as `--radius-{sm,md,lg,xl}` with literal values, replacing the single `--radius` and its three derived `--radius-{sm,md,lg}` values; the scale SHALL NOT include `DEFAULT` or `full`, because both are unreachable (Tailwind emits them as literals that do not read the token) and would be tokens with no consumer.
- THE SYSTEM SHALL keep the existing utilities and guarantees in `globals.css`: `tap-target` (44×44 px), `pb-safe`, the visible focus indicator, and the `prefers-reduced-motion: reduce` block that disables animations and transitions.

### Borders

- THE SYSTEM SHALL declare `--border` as the decorative 1 px hairline from the design export, coherent in both themes; the contrast between `--border` and `--background` is intentionally below 3:1, because the line is decorative and never carries information on its own.
- THE SYSTEM SHALL declare `--input` with a value that meets the 3:1 threshold against its surface, distinct from `--border`, because WCAG 1.4.11 requires 3:1 at the visual edge of a UI component.

### Operational-state and severity palette

- THE SYSTEM SHALL keep the badge colour palette in exactly one place (`lib/ui/status-tone.ts`: the `Tone` union and its `TONE_BADGE_CLASS` map) and SHALL NOT let a feature restate the Tailwind classes; each entry is one string with no `dark:` variant, relying on `--state-*` anchors plus Tailwind v4's `color-mix`-based opacity modifiers so both themes come from the same string.
- THE SYSTEM SHALL define a token for the gray family of PRD §9.1 (`state-neutral`, `state-neutral-text`), which the design export does not name but the operational-state machine needs.
- THE SYSTEM SHALL unify the severity vocabulary of `features/incidents/` into a single `Record<IncidentSeverity, Tone>` mapping in its own domain (`features/incidents/lib/severity-tone.ts`), satisfying the «one place for the palette» rule of `frontend-foundation` without merging the severity vocabulary into `lib/ui/`: incident severity and PRD §9.1 operational state mean different things and only share the palette.
- WHEN painting a severity badge with the dark theme active, THE SYSTEM SHALL use a background/text pair that meets AA contrast.

### Raw scales and `dark:` are forbidden in non-test code

- THE SYSTEM SHALL leave `frontend/` with no reference to a Tailwind numeric colour scale (`bg-*-100`, `text-*-800`, `dark:bg-*-950`, …) in non-test code, and this SHALL be verifiable by `test/color-tokens.test.ts`, whose output is the registered record of the change.
- THE SYSTEM SHALL leave `frontend/` with no `dark:` variant or any other variant that keys off `prefers-color-scheme` in non-test code; consumers follow the resolved theme by token, not by media query.
- THE SYSTEM SHALL fail the guard if a non-test file names a colour utility against a token that the CSS does not declare, so a class like `bg-card` against an undeclared `--color-card` is caught instead of silently falling back to the page background.

## Key files

- `frontend/app/globals.css` — the three token-bearing blocks (light on `:root`, dark via media query, dark via attribute), `@theme`/`@theme inline` for Tailwind v4, `@layer base`, `prefers-reduced-motion`, `tap-target`, `pb-safe`, focus indicator.
- `frontend/app/layout.tsx` — root layout that paints `<html lang data-theme className={…font variables…}>` from the resolved locale and theme, and registers `next/font` for Inter and JetBrains Mono.
- `frontend/lib/config/constants.ts` — `THEME_COOKIE`, `SUPPORTED_THEMES`, `Theme`, `isTheme` alongside the locale declarations.
- `frontend/lib/theme/theme.ts` — `resolveTheme()` (isomorphic) and the `THEME_ATTRIBUTE` constant.
- `frontend/lib/theme/server.ts` — `getServerTheme()` server-only, mirrors `getServerLocale`.
- `frontend/features/shell/components/theme-switcher.tsx` — the three-state accessible control mounted in `Topbar`'s end slot; the `LocaleSwitcher` was reshaped into a single-button action control so the two controls do not compete for space in the topbar.
- `frontend/features/shell/components/topbar.tsx` — async Server Component that calls `getServerTheme()` and mounts the switcher.
- `frontend/features/shell/components/{workspace,cleaner,technician,public,guest}-shell.tsx` — the five shells that invoke `await Topbar(…)` so the async component resolves at server render.
- `frontend/lib/ui/status-tone.ts` — the single badge palette (`Tone`, `TONE_BADGE_CLASS`), one string per tone with no `dark:` variant.
- `frontend/features/incidents/lib/severity-tone.ts` — `Record<IncidentSeverity, Tone>` and `severityColorGroup()` replacing the two duplicated `SEVERITY_COLOR` tables.
- `frontend/locales/{es,en}/navigation.json` — `themeSwitcher.{label,light,dark,system}`.
- `frontend/test/color-tokens.test.ts` — the five-comparison guard (raw scales, `dark:`/`prefers-color-scheme` variants, declared-token coverage, arbitrary values, inline hex) with patterns extracted into `test/color-tokens.ts`.
- `frontend/app/globals.tokens.test.ts` — asserts the three blocks declare the same set of token names and that the two dark blocks declare identical values.
- `frontend/app/globals.contrast.test.ts` — parses the token values, computes WCAG ratios for every declared pair, and fails below threshold.
- `frontend/test/theme-client-state.test.ts` — pins the cookie + attribute + `aria-pressed` triad of the switcher.
- `frontend/test/wcag-contrast.ts`, `frontend/test/css-tokens.ts` — shared helpers for the audit and the guard.
