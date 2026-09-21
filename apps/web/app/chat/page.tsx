"use client";

import { MedicalDisclaimer } from "@/components/MedicalDisclaimer";
import { useEffect, useRef, useState } from "react";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import type {
  ChatHistoryItem,
  ChatMessageResponse,
  ChatProposal,
  FoodDetail,
} from "@/lib/types";
import { Skeleton } from "@/components/ui/states";
import {
  AiWaiting,
  QuotaBadge,
  ThinkingDots,
  useAiQuota,
  useElapsedSeconds,
} from "@/components/ui/AiWaiting";

const bubbleBase = "max-w-[85%] rounded-2xl px-4 py-2 text-sm";
const userBubble = `${bubbleBase} self-end bg-[var(--color-primary)] text-[var(--color-on-primary)]`;
const assistantBubble = `${bubbleBase} self-start border border-[var(--color-border)]`;

export default function ChatPage() {
  const [history, setHistory] = useState<ChatHistoryItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsConsent, setNeedsConsent] = useState(false);
  const [proposal, setProposal] = useState<ChatProposal | null>(null);
  const [foodNames, setFoodNames] = useState<Record<string, string>>({});
  const [deciding, setDeciding] = useState(false);
  const [recording, setRecording] = useState(false);
  const [micUnsupported, setMicUnsupported] = useState(false);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const elapsed = useElapsedSeconds(sending);
  const { quota, reload: reloadQuota } = useAiQuota("chat");

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  async function loadHistory() {
    try {
      const items = await apiFetch<ChatHistoryItem[]>("/api/chat/history?limit=100");
      // El backend devuelve más reciente primero (sección 7.9); la
      // conversación se lee de arriba a abajo.
      setHistory([...items].reverse());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoadingHistory(false);
    }
  }

  useEffect(() => {
    void loadHistory();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history, proposal]);

  async function resolveFoodNames(p: ChatProposal) {
    if (p.scope !== "day") return;
    const missing = new Set<string>();
    for (const meal of p.payload.meals) {
      for (const item of meal.items) {
        if (!(item.food_id in foodNames)) missing.add(item.food_id);
      }
    }
    if (missing.size === 0) return;
    const entries = await Promise.all(
      [...missing].map(async (id) => {
        try {
          const food = await apiFetch<FoodDetail>(`/api/foods/${id}`);
          return [id, food.name_es] as const;
        } catch {
          return [id, "Alimento"] as const;
        }
      }),
    );
    setFoodNames((prev) => ({ ...prev, ...Object.fromEntries(entries) }));
  }

  async function send(body: FormData, pending?: string) {
    if (sending) return;
    setSending(true);
    setError(null);
    setNeedsConsent(false);
    // El mensaje se ve en cuanto se envía, sin esperar a que vuelva el historial: antes
    // desaparecía del cuadro de texto y no aparecía en la conversación hasta que el modelo
    // contestaba, así que durante la espera no había ni rastro de lo escrito.
    setPendingMessage(pending ?? null);
    try {
      const res = await apiFetch<ChatMessageResponse>("/api/chat/message", {
        method: "POST",
        body,
      });
      setProposal(res.proposal);
      if (res.proposal) await resolveFoodNames(res.proposal);
      await loadHistory();
    } catch (err) {
      if (err instanceof ApiError && err.code === "AI_CONSENT_REQUIRED") {
        setNeedsConsent(true);
      } else if (
        err instanceof ApiError &&
        (err.code === "CHAT_TIMEOUT" || err.status === 504)
      ) {
        // Cloudflare sustituye el cuerpo de un 504 del origen por su propia
        // página, así que el código del JSON puede no llegar — el estado
        // HTTP basta para saber que fue el timeout del turno.
        setError(
          "La respuesta está tardando demasiado. Tu mensaje ya se ha guardado — puedes " +
            "revisar el historial en un momento o volver a intentarlo.",
        );
        await loadHistory();
      } else if (err instanceof ApiError && err.status === 429) {
        setError("Has alcanzado tu límite de mensajes de hoy. Vuelve a intentarlo mañana.");
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setSending(false);
      setPendingMessage(null);
      reloadQuota();
    }
  }

  async function onSendText(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    // El `disabled` del botón no basta: el Enter del teclado puede llegar igual, y cada
    // envío gasta uno de los mensajes del día aunque el texto sea idéntico al anterior.
    if (!trimmed || sending) return;
    const body = new FormData();
    body.set("text", trimmed);
    setText("");
    await send(body, trimmed);
  }

  async function acceptConsent() {
    try {
      await apiFetch("/api/consents", {
        method: "POST",
        body: JSON.stringify({ kind: "ai_processing", version: "v1" }),
      });
      setNeedsConsent(false);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function startRecording() {
    if (typeof window === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setMicUnsupported(true);
      return;
    }
    const mimeType = "audio/webm";
    if (typeof MediaRecorder !== "undefined" && !MediaRecorder.isTypeSupported(mimeType)) {
      setMicUnsupported(true);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType });
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: mimeType });
        const body = new FormData();
        body.set("audio", blob, "nota.webm");
        void send(body);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch {
      setMicUnsupported(true);
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  }

  async function decideProposal(decision: "approve" | "reject") {
    if (!proposal) return;
    setDeciding(true);
    setError(null);
    try {
      await apiFetch(`/api/ai/proposals/${proposal.ai_proposal_id}/${decision}`, {
        method: "POST",
      });
      setProposal(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setDeciding(false);
    }
  }

  return (
    <main className="flex h-[calc(100dvh-11.6rem)] max-w-2xl flex-col gap-4 md:h-[calc(100dvh-5rem)]">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Chat</h1>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <p className="text-sm text-neutral-500">
            Pídeme cambios sobre la marcha — nunca aplico nada sin que lo confirmes.
          </p>
          <QuotaBadge quota={quota} />
        </div>
        <div className="mt-2">
          <MedicalDisclaimer>
            El chat no da consejo médico. Los cambios que propone son estimaciones que tú
            confirmas; consulta con un profesional ante cualquier duda de salud.
          </MedicalDisclaimer>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-2 overflow-y-auto rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3">
        {loadingHistory && <Skeleton lines={3} />}
        {!loadingHistory && history.length === 0 && (
          <p className="text-sm text-neutral-500">
            Escríbeme algo como «cámbiame la cena de hoy, tengo salmón» o «¿qué llevo hoy de
            proteína?».
          </p>
        )}
        <div className="flex flex-col gap-2">
          {history.map((m) => (
            <div key={m.id} className={m.role === "user" ? userBubble : assistantBubble}>
              {m.source === "voice" && (
                <span className="mr-1 text-xs opacity-70" title="Enviado por voz">
                  🎤
                </span>
              )}
              {m.content}
            </div>
          ))}
          {pendingMessage && (
            <div className={`${userBubble} opacity-70`}>{pendingMessage}</div>
          )}
          {sending && (
            <div className={`${assistantBubble} flex items-center gap-2 text-neutral-500`}>
              <ThinkingDots />
              <span>Pensando…</span>
            </div>
          )}
        </div>

        {proposal && (
          <div className="mt-2 self-start rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950">
            <p className="font-medium">Propuesta de cambio</p>
            {proposal.scope === "day" ? (
              <ul className="mt-2 flex flex-col gap-1">
                {proposal.payload.meals.map((meal, mi) => (
                  <li key={mi}>
                    <span className="font-medium">{meal.meal_type}:</span>{" "}
                    {meal.items
                      .map((item) => `${foodNames[item.food_id] ?? "…"} (${Math.round(item.grams)} g)`)
                      .join(", ")}
                  </li>
                ))}
              </ul>
            ) : (
              <ul className="mt-2 flex flex-col gap-1">
                {proposal.payload.items.map((item, i) => (
                  <li key={i}>
                    {item.food_name} — {Math.round(item.quantity_g)} g
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                disabled={deciding}
                onClick={() => void decideProposal("approve")}
                className="rounded-full bg-[var(--color-primary)] px-3 py-1.5 text-sm text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
              >
                Aprobar
              </button>
              <button
                type="button"
                disabled={deciding}
                onClick={() => void decideProposal("reject")}
                className="rounded-full border border-[var(--color-border-strong)] font-medium px-3 py-1.5 text-sm disabled:opacity-60"
              >
                Rechazar
              </button>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {sending && <AiWaiting task="chat" elapsedSeconds={elapsed} label="Preparando la respuesta" />}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {needsConsent && (
        <div className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3 text-sm">
          <p className="mb-2">
            Antes de usar el chat, acepta que tus mensajes se procesen con Claude (nunca tu
            nombre, email ni historial identificable).
          </p>
          <button
            type="button"
            onClick={() => void acceptConsent()}
            className="rounded-full bg-[var(--color-primary)] px-3 py-1.5 text-sm text-[var(--color-on-primary)] font-semibold hover:bg-[var(--color-primary-hover)]"
          >
            Aceptar y continuar
          </button>
        </div>
      )}
      {micUnsupported && (
        <p className="text-xs text-neutral-500">
          Tu navegador no admite grabar notas de voz aquí — puedes escribir tu mensaje.
        </p>
      )}

      <form onSubmit={onSendText} className="flex items-end gap-2">
        <textarea
          className="min-h-[2.5rem] flex-1 resize-none rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2 text-sm"
          rows={1}
          placeholder="Escribe un mensaje…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={sending || recording}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void onSendText(e);
            }
          }}
        />
        <button
          type="button"
          onClick={() => void (recording ? stopRecording() : startRecording())}
          disabled={sending}
          className={`rounded-lg border px-3 py-2 text-sm disabled:opacity-60 ${
            recording
              ? "border-red-400 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950"
              : "border-[var(--color-border-strong)]"
          }`}
          title={recording ? "Detener grabación" : "Grabar nota de voz"}
        >
          {recording ? "⏹" : "🎤"}
        </button>
        <button
          type="submit"
          disabled={sending || recording || !text.trim() || quota?.remaining === 0}
          className="inline-flex items-center gap-2 rounded-full bg-[var(--color-primary)] px-4 py-2 text-sm text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
        >
          {sending ? <ThinkingDots /> : null}
          {sending ? "Enviando" : "Enviar"}
        </button>
      </form>
    </main>
  );
}
