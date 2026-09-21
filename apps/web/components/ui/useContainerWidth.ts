"use client";

import { useEffect, useRef, useState } from "react";

/** Ancho real en píxeles del elemento al que se enganche.
 *
 * Las gráficas lo necesitan para dibujar con un `viewBox` del mismo tamaño que el hueco que
 * ocupan: con un `viewBox` fijo escalado al 100 %, en un móvil todo se encoge a la vez y las
 * etiquetas de los ejes acaban en letra de 6 píxeles, ilegible. Midiendo, una unidad del SVG
 * es un píxel y el texto sale del tamaño que se pidió.
 *
 * `fallback` es lo que se usa en el primer render y al pintar en el servidor, donde todavía
 * no hay nada que medir. */
export function useContainerWidth(fallback = 720) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(fallback);

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.round(entry.contentRect.width);
      if (next > 0) setWidth(next);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}
