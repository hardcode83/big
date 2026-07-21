/**
 * Product wordmark. Server Component: the label is resolved on the server and
 * passed in (design D9/D13).
 */
export function Brand({ label }: { label: string }) {
  return <span className="text-base font-semibold text-foreground">{label}</span>;
}
