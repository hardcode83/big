import { redirect } from "next/navigation";

export default function RootPage() {
  // Stable entry redirect to the primary operational surface (design D3).
  redirect("/dashboard");
}
