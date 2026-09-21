import { redirect } from "next/navigation";
import { MoreHub } from "@/components/MoreHub";
import { getCurrentUser } from "@/lib/session";

export const metadata = { title: "Más · MyFood" };

export default async function MorePage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  return <MoreHub user={user} />;
}
