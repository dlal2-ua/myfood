"use client";

import { ArrowLeftRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { FoodImage } from "@/components/FoodImage";
import { ApiError, apiFetch } from "@/lib/api";
import type { SimilarFoodsResponse } from "@/lib/types";

/** Alternativas para cambiar un alimento por otro parecido.
 *
 * El backend lo calcula desde el día uno —distancia sobre `food_vectors`, mismo grupo
 * alimentario, restricciones del usuario respetadas, y los gramos ya ajustados para conservar
 * las calorías— y hasta ahora ninguna pantalla lo enseñaba. Los gramos importan: sustituir
 * 100 g de una cosa por 100 g de otra no conserva nada, y por eso cada alternativa viene con
 * su cantidad equivalente ya calculada.
 */
export function SimilarFoods({ foodId, grams }: { foodId: string; grams: number }) {
  const [items, setItems] = useState<SimilarFoodsResponse["items"] | null>(null);
  const [sinVector, setSinVector] = useState(false);

  useEffect(() => {
    let cancelado = false;
    apiFetch<SimilarFoodsResponse>(
      `/api/foods/${foodId}/similar?limit=3&keep=kcal&grams=${Math.round(grams)}`,
    )
      .then((res) => !cancelado && setItems(res.items))
      .catch((err) => {
        if (cancelado) return;
        // Un alimento sin vector nutricional no es un error que merezca una alerta: es que
        // todavía no se ha calculado. Simplemente no se ofrecen alternativas.
        if (err instanceof ApiError && err.code === "FOOD_VECTOR_NOT_FOUND") setSinVector(true);
        setItems([]);
      });
    return () => {
      cancelado = true;
    };
  }, [foodId, grams]);

  if (sinVector || (items !== null && items.length === 0)) return null;

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <ArrowLeftRight size={18} aria-hidden="true" className="text-[var(--color-primary)]" />
          Si te apetece otra cosa
        </h2>
        <p className="text-sm text-[var(--color-muted)]">
          Parecidos en nutrientes, con la cantidad ya ajustada para que sumen lo mismo que{" "}
          {Math.round(grams)} g de este.
        </p>
      </div>
      {items === null ? (
        <div className="h-20 animate-pulse rounded-[var(--radius-card)] bg-[var(--color-surface-2)]" />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((item) => (
            <li key={item.id}>
              <Link
                href={`/foods/${item.id}`}
                className="flex items-center gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] p-3 shadow-[var(--shadow-card)] hover:bg-[var(--color-surface-2)]"
              >
                <FoodImage foodId={item.id} size={100} px={48} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{item.name_es}</span>
                  {item.brand && (
                    <span className="block truncate text-xs text-[var(--color-muted)]">
                      {item.brand}
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-right">
                  <span className="block text-sm font-bold">{Math.round(item.grams)} g</span>
                  {item.kcal_100g != null && (
                    <span className="block text-xs text-[var(--color-muted)]">
                      {Math.round((item.kcal_100g * item.grams) / 100)} kcal
                    </span>
                  )}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
