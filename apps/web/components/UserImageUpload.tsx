"use client";

import { useRef, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";

const MAX_BYTES = 10 * 1024 * 1024;

/** Foto propia de una receta o un suplemento: se sube al servidor, que la reescala a 1024 px y le
 * quita el EXIF (ubicación incluida). El original no se guarda. */
export function UserImageUpload({
  imageUrl,
  endpoint,
  alt,
  onChanged,
}: {
  imageUrl: string | null | undefined;
  /** Ruta del API sin `/image`, p. ej. `/api/recipes/<id>`. */
  endpoint: string;
  alt: string;
  onChanged: () => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    if (file.size > MAX_BYTES) {
      setError("La imagen supera el máximo de 10 MB.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.set("file", file);
      await apiFetch(`${endpoint}/image`, { method: "PUT", body });
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`${endpoint}/image`, { method: "DELETE" });
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      {imageUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={imageUrl} alt={alt} className="h-20 w-20 rounded-lg object-cover" />
      ) : (
        <div
          className="flex h-20 w-20 items-center justify-center rounded-lg bg-neutral-100 text-xs text-neutral-400 dark:bg-neutral-800"
          aria-hidden="true"
        >
          Sin foto
        </div>
      )}
      <div className="flex flex-col gap-1 text-sm">
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/heic"
          className="sr-only"
          id={`${endpoint}-file`}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
          }}
        />
        <label
          htmlFor={`${endpoint}-file`}
          className={`w-fit cursor-pointer rounded-full border border-[var(--color-border-strong)] font-medium px-3 py-1 ${busy ? "opacity-60" : ""}`}
        >
          {busy ? "Subiendo…" : imageUrl ? "Cambiar foto" : "Subir foto"}
        </label>
        {imageUrl && (
          <button
            type="button"
            onClick={() => void remove()}
            disabled={busy}
            className="w-fit text-neutral-500 underline"
          >
            Quitar
          </button>
        )}
        {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
      </div>
    </div>
  );
}
