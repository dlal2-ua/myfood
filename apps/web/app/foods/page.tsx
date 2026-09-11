"use client";

import { useRouter } from "next/navigation";
import { FoodSearchBox } from "@/components/FoodSearchBox";

export default function FoodsPage() {
  const router = useRouter();

  return (
    <main className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Alimentos</h1>
      <FoodSearchBox onSelect={(item) => router.push(`/foods/${item.id}`)} />
    </main>
  );
}
