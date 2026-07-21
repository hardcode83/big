/**
 * "Skip to content" link — first focusable element, visible on focus (D14).
 * Server Component: its label is resolved on the server and passed in, so no
 * client i18n hook ships for it (design D9).
 */
export function SkipLink({ label }: { label: string }) {
  return (
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:shadow"
    >
      {label}
    </a>
  );
}
