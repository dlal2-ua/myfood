import { LocalNotifications } from "@capacitor/local-notifications";
import { apiFetch } from "@/lib/api";
import { isNativeApp } from "@/lib/healthConnect";
import type { NotificationRule } from "@/lib/types";

/**
 * Notificaciones locales vía Capacitor (sección "Notificaciones push",
 * criterio de aceptación de la Fase 6: "las notificaciones locales
 * funcionan sin conexión"). El worker ya envía Web Push con VAPID
 * (Fase 3) — esto es la vía adicional, más fiable en el móvil porque no
 * depende de que el dispositivo tenga datos en ese momento exacto.
 *
 * Reutiliza las mismas `notification_rules` que ya gestiona el backend
 * (`GET /api/notification-rules`); el reparto de horarios por `kind` es
 * el mismo criterio que `myfood/notifications.py::due_times_for_rule` —
 * duplicado aquí a propósito: la programación tiene que ocurrir en el
 * dispositivo (Capacitor no puede llamar a Python), así que no hay forma
 * de compartir el código real, solo el criterio.
 */

interface DueTime {
  hour: number;
  minute: number;
}

function dueTimesForRule(rule: NotificationRule): DueTime[] {
  const parse = (value: string): DueTime => {
    const [hh, mm] = value.split(":").map(Number);
    return { hour: hh, minute: mm };
  };
  if (rule.kind === "water") {
    const times = (rule.schedule.times as string[] | undefined) ?? [];
    return times.map(parse);
  }
  if (rule.kind === "supplement") {
    const raw = rule.schedule.time as string | undefined;
    return raw ? [parse(raw)] : [];
  }
  return [];
}

function inQuietHours(t: DueTime, quietFrom: string, quietTo: string): boolean {
  const minutes = t.hour * 60 + t.minute;
  const [fromH, fromM] = quietFrom.split(":").map(Number);
  const [toH, toM] = quietTo.split(":").map(Number);
  const from = fromH * 60 + fromM;
  const to = toH * 60 + toM;
  if (from <= to) return minutes >= from && minutes < to;
  return minutes >= from || minutes < to; // rango que cruza medianoche
}

function messageForRule(rule: NotificationRule): string {
  const custom = rule.schedule.message as string | undefined;
  if (custom) return custom;
  if (rule.kind === "water") return "Hora de beber agua.";
  if (rule.kind === "supplement") return "Toca un suplemento.";
  return "Tienes un recordatorio pendiente.";
}

/** Entero estable de 32 bits a partir de una cadena — Capacitor exige un
 * `id` numérico por notificación programada; derivarlo de
 * `ruleId:hora:minuto` deja reprogramar sin acumular duplicados. */
function stableId(text: string): number {
  let hash = 0;
  for (let i = 0; i < text.length; i++) {
    hash = (hash * 31 + text.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) || 1;
}

export async function syncLocalNotifications(): Promise<void> {
  if (!isNativeApp()) return;

  const permission = await LocalNotifications.checkPermissions();
  if (permission.display !== "granted") {
    const requested = await LocalNotifications.requestPermissions();
    if (requested.display !== "granted") return;
  }

  const pending = await LocalNotifications.getPending();
  if (pending.notifications.length > 0) {
    await LocalNotifications.cancel({
      notifications: pending.notifications.map((n) => ({ id: n.id })),
    });
  }

  const rules = await apiFetch<NotificationRule[]>("/api/notification-rules");
  const toSchedule = rules
    .filter((rule) => rule.is_enabled)
    .flatMap((rule) =>
      dueTimesForRule(rule)
        .filter((t) => !inQuietHours(t, rule.quiet_from, rule.quiet_to))
        .map((t) => ({ rule, time: t })),
    );

  if (toSchedule.length === 0) return;

  await LocalNotifications.schedule({
    notifications: toSchedule.map(({ rule, time }) => ({
      id: stableId(`${rule.id}:${time.hour}:${time.minute}`),
      title: "MyFood",
      body: messageForRule(rule),
      schedule: { on: { hour: time.hour, minute: time.minute }, allowWhileIdle: true },
    })),
  });
}
