export const dynamic = "force-dynamic";

async function getBackendHealth(): Promise<"ok" | "ko"> {
  try {
    const res = await fetch(`${process.env.BACKEND_INTERNAL_URL}/health`, {
      cache: "no-store",
    });
    if (!res.ok) return "ko";
    const data = await res.json();
    return data.status === "ok" ? "ok" : "ko";
  } catch {
    return "ko";
  }
}

export default async function Page() {
  const status = await getBackendHealth();

  return (
    <main className="flex min-h-screen items-center justify-center">
      <p data-testid="backend-status">backend: {status}</p>
    </main>
  );
}
