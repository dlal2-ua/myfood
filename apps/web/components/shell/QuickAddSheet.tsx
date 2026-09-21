"use client";

import Link from "next/link";
import { useCurrentUserId } from "@/components/CurrentUser";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { errorMessage } from "@/lib/api";
import { localDateIso } from "@/lib/dates";
import { QUICK_ACTIONS } from "@/lib/nav";
import { submitOrQueue } from "@/lib/offlineQueue";

const GLASS_ML = 200;
export const DATA_CHANGED_EVENT = "myfood:data-changed";

/** Hoja de acciones rápidas (el botón «+» del centro de la barra inferior): lo que más se hace
 * a diario, a un toque desde cualquier pantalla. */
export function QuickAddSheet({
  open,
  onClose,
  onNotice,
}: {
  open: boolean;
  onClose: () => void;
  onNotice: (message: string) => void;
}) {
  const userId = useCurrentUserId();

  async function addWater() {
    onClose();
    try {
      const outcome = await submitOrQueue({
        userId: userId ?? "",
        kind: "water",
        label: `Agua — ${GLASS_ML} ml (${localDateIso()})`,
        payload: { log_date: localDateIso(), ml: GLASS_ML },
      });
      onNotice(
        outcome.queued
          ? "Sin conexión: guardado en el dispositivo, se registrará al volver la red."
          : `Añadidos ${GLASS_ML} ml de agua.`,
      );
      if (!outcome.queued) window.dispatchEvent(new Event(DATA_CHANGED_EVENT));
    } catch (err) {
      onNotice(errorMessage(err));
    }
  }

  return (
    <BottomSheet open={open} onClose={onClose} title="Añadir">
      <ul className="grid grid-cols-3 gap-2.5">
        {QUICK_ACTIONS.map((action) => {
          const Icon = action.icon;
          const tile =
            "flex h-full min-h-[6.25rem] w-full flex-col items-center justify-center gap-2 rounded-2xl bg-[var(--color-surface-2)] p-2 text-center text-[13px] font-semibold leading-tight transition-colors hover:bg-[var(--color-primary-soft)]";
          const icon = (
            <span className="grid h-11 w-11 place-items-center rounded-full bg-[var(--color-primary-soft)] text-[var(--color-primary)]">
              <Icon size={22} aria-hidden="true" />
            </span>
          );
          return (
            <li key={action.key}>
              {action.href ? (
                <Link href={action.href} onClick={onClose} className={tile}>
                  {icon}
                  {action.label}
                </Link>
              ) : (
                <button type="button" onClick={() => void addWater()} className={tile}>
                  {icon}
                  {action.label}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </BottomSheet>
  );
}
