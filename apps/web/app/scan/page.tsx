"use client";

import { Html5Qrcode, Html5QrcodeSupportedFormats } from "html5-qrcode";
import { useEffect, useRef, useState } from "react";
import { AddToLogForm } from "@/components/AddToLogForm";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import type { FoodDetail } from "@/lib/types";

const SCANNER_ELEMENT_ID = "barcode-scanner";

const inputClass =
  "rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900";

interface ManualForm {
  name_es: string;
  brand: string;
  kcal_100g: string;
  protein_100g: string;
  fat_100g: string;
  carbs_100g: string;
}

const EMPTY_MANUAL: ManualForm = {
  name_es: "",
  brand: "",
  kcal_100g: "",
  protein_100g: "0",
  fat_100g: "0",
  carbs_100g: "0",
};

/** Flujo de escaneo (Fase 2 del roadmap, documento 2 sección 11.2):
 * cámara -> `GET /foods/barcode/{ean}` (BD local -> OFF en vivo) -> si nada
 * lo tiene, alta manual con los datos reales de la etiqueta. */
export default function ScanPage() {
  const [scanning, setScanning] = useState(true);
  const [scannerError, setScannerError] = useState<string | null>(null);
  const [barcode, setBarcode] = useState<string | null>(null);
  const [food, setFood] = useState<FoodDetail | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [manual, setManual] = useState<ManualForm>(EMPTY_MANUAL);
  const [manualError, setManualError] = useState<string | null>(null);
  const [manualSaving, setManualSaving] = useState(false);
  const scannerRef = useRef<Html5Qrcode | null>(null);
  const handledRef = useRef(false);

  useEffect(() => {
    if (!scanning) return;
    handledRef.current = false;
    const scanner = new Html5Qrcode(SCANNER_ELEMENT_ID, {
      formatsToSupport: [
        Html5QrcodeSupportedFormats.EAN_13,
        Html5QrcodeSupportedFormats.EAN_8,
        Html5QrcodeSupportedFormats.UPC_A,
        Html5QrcodeSupportedFormats.UPC_E,
      ],
      verbose: false,
    });
    scannerRef.current = scanner;

    scanner
      .start(
        { facingMode: "environment" },
        { fps: 10, qrbox: { width: 250, height: 150 } },
        (decodedText) => {
          if (handledRef.current) return; // un código puede decodificarse varias veces por segundo
          handledRef.current = true;
          void onScanned(decodedText);
        },
        () => {
          // callback de "no se detectó código en este frame" — se dispara
          // constantemente mientras se apunta la cámara, es esperado, se ignora.
        },
      )
      .catch((err) => setScannerError(errorMessage(err)));

    return () => {
      scanner
        .stop()
        .catch(() => {})
        .finally(() => scanner.clear());
    };
  }, [scanning]);

  async function onScanned(decodedText: string) {
    setScanning(false);
    await scannerRef.current?.stop().catch(() => {});
    setBarcode(decodedText);
    setLookupLoading(true);
    setNotFound(false);
    setFood(null);
    try {
      const result = await apiFetch<FoodDetail>(`/api/foods/barcode/${decodedText}`);
      setFood(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
      } else {
        setScannerError(errorMessage(err));
      }
    } finally {
      setLookupLoading(false);
    }
  }

  function onRescan() {
    setBarcode(null);
    setFood(null);
    setNotFound(false);
    setScannerError(null);
    setManual(EMPTY_MANUAL);
    setManualError(null);
    setScanning(true);
  }

  async function onManualSubmit(e: React.FormEvent) {
    e.preventDefault();
    setManualSaving(true);
    setManualError(null);
    try {
      const created = await apiFetch<FoodDetail>("/api/foods/manual", {
        method: "POST",
        body: JSON.stringify({
          barcode_ean: barcode,
          name_es: manual.name_es,
          brand: manual.brand || null,
          kcal_100g: Number(manual.kcal_100g),
          protein_100g: Number(manual.protein_100g),
          fat_100g: Number(manual.fat_100g),
          carbs_100g: Number(manual.carbs_100g),
        }),
      });
      setFood(created);
      setNotFound(false);
    } catch (err) {
      setManualError(errorMessage(err));
    } finally {
      setManualSaving(false);
    }
  }

  return (
    <main className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Escanear producto</h1>

      {scanning && (
        <div>
          <div id={SCANNER_ELEMENT_ID} className="mx-auto max-w-sm overflow-hidden rounded-lg" />
          <p className="mt-2 text-sm text-neutral-500">
            Apunta la cámara al código de barras del producto.
          </p>
        </div>
      )}

      {scannerError && <p className="text-sm text-red-600">{scannerError}</p>}
      {!scanning && lookupLoading && <p className="text-sm text-neutral-500">Buscando…</p>}

      {food && (
        <>
          <div>
            <h2 className="text-lg font-semibold">{food.name_es}</h2>
            {food.brand && <p className="text-sm text-neutral-500">{food.brand}</p>}
            <p className="text-sm text-neutral-500">
              {food.kcal_100g} kcal · {food.protein_100g} g prot. / 100 g
            </p>
          </div>
          <AddToLogForm foodId={food.id} />
        </>
      )}

      {notFound && !food && (
        <section>
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            No encontramos el código <strong>{barcode}</strong> en el catálogo ni en Open Food
            Facts. Puedes darlo de alta a mano con los datos reales de la etiqueta.
          </p>
          <form onSubmit={onManualSubmit} className="mt-4 flex max-w-sm flex-col gap-3">
            <label className="flex flex-col gap-1 text-sm">
              Nombre
              <input
                required
                className={inputClass}
                value={manual.name_es}
                onChange={(e) => setManual({ ...manual, name_es: e.target.value })}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Marca (opcional)
              <input
                className={inputClass}
                value={manual.brand}
                onChange={(e) => setManual({ ...manual, brand: e.target.value })}
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1 text-sm">
                kcal / 100 g
                <input
                  type="number"
                  required
                  min={1}
                  max={900}
                  step="0.1"
                  className={inputClass}
                  value={manual.kcal_100g}
                  onChange={(e) => setManual({ ...manual, kcal_100g: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                Proteína (g)
                <input
                  type="number"
                  min={0}
                  step="0.1"
                  className={inputClass}
                  value={manual.protein_100g}
                  onChange={(e) => setManual({ ...manual, protein_100g: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                Grasa (g)
                <input
                  type="number"
                  min={0}
                  step="0.1"
                  className={inputClass}
                  value={manual.fat_100g}
                  onChange={(e) => setManual({ ...manual, fat_100g: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                Carbohidratos (g)
                <input
                  type="number"
                  min={0}
                  step="0.1"
                  className={inputClass}
                  value={manual.carbs_100g}
                  onChange={(e) => setManual({ ...manual, carbs_100g: e.target.value })}
                />
              </label>
            </div>
            <button
              type="submit"
              disabled={manualSaving}
              className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
            >
              {manualSaving ? "Guardando…" : "Guardar y añadir al catálogo"}
            </button>
          </form>
          {manualError && <p className="mt-2 text-sm text-red-600">{manualError}</p>}
        </section>
      )}

      {!scanning && (
        <button type="button" onClick={onRescan} className="self-start text-sm underline">
          Escanear otro código
        </button>
      )}
    </main>
  );
}
