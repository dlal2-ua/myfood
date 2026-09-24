"use client";

import { History, Mic, Plus, Square, Trash2, X } from "lucide-react";
import Link from "next/link";
import { MedicalDisclaimer } from "@/components/MedicalDisclaimer";
import { DiaryProposalCard } from "@/components/chat/DiaryProposalCard";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import type {
  ChatConversationSummary,
  ChatHistoryItem,
  ChatMessageResponse,
  ChatProposal,
  FoodDetail,
} from "@/lib/types";
import { BottomSheet } from "@/components/ui/BottomSheet";
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

/** Se corta sola: 15 MB de audio se alcanzan sin darse cuenta y Whisper tarda más cuanto más
 * larga es la nota. Dos minutos son de sobra para contar lo que se ha comido. */
const MAX_RECORDING_SECONDS = 120;

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function conversationLabel(c: ChatConversationSummary): string {
  if (c.title) return c.title;
  return "Conversación vacía";
}

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
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [showDiaryLink, setShowDiaryLink] = useState(false);
  const [conversations, setConversations] = useState<ChatConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const elapsed = useElapsedSeconds(sending);
  const { quota, reload: reloadQuota } = useAiQuota("chat");

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const cancelledRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  // El backend ya devuelve del más antiguo al más reciente, ordenado por `seq` y no por
  // fecha: antes los dos mensajes de un turno compartían `created_at` al microsegundo, el
  // orden empataba y al darle la vuelta aquí la respuesta salía encima de la pregunta.
  const loadHistory = useCallback(async (id?: string | null) => {
    const target = id ?? conversationId;
    const query = target ? `&conversation_id=${target}` : "";
    try {
      setHistory(await apiFetch<ChatHistoryItem[]>(`/api/chat/history?limit=100${query}`));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoadingHistory(false);
    }
  }, [conversationId]);

  const loadConversations = useCallback(async () => {
    try {
      const items = await apiFetch<ChatConversationSummary[]>("/api/chat/conversations");
      setConversations(items);
      // Sin hilo elegido, el activo es el más reciente — el mismo que usa el backend cuando
      // no se le pasa ninguno, así que la vista y lo que se escribe no pueden desalinearse.
      setConversationId((current) => current ?? items[0]?.id ?? null);
    } catch {
      // El selector es un extra: si falla, el chat sigue funcionando sobre el hilo activo.
    }
  }, []);

  useEffect(() => {
    void loadHistory();
    void loadConversations();
    // Solo al montar: después se recarga a mano al cambiar de hilo o al enviar.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // El aviso caduca solo, como el del shell: antes «Empezamos de cero.» se quedaba para
  // siempre debajo de los botones.
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => {
      setNotice(null);
      setShowDiaryLink(false);
    }, 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (!recording) return;
    const timer = window.setInterval(() => setRecordingSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(timer);
  }, [recording]);

  useEffect(() => {
    if (recording && recordingSeconds >= MAX_RECORDING_SECONDS) stopRecording();
  }, [recording, recordingSeconds]);

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
    if (conversationId) body.set("conversation_id", conversationId);
    try {
      const res = await apiFetch<ChatMessageResponse>("/api/chat/message", {
        method: "POST",
        body,
      });
      setProposal(res.proposal);
      if (res.proposal) await resolveFoodNames(res.proposal);
      await loadHistory();
      // El título del hilo lo pone el primer mensaje: hasta ahora la lista lo mostraba vacío.
      void loadConversations();
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

  /** Empieza un hilo nuevo sin borrar nada: el anterior sigue en el selector. */
  async function onNewConversation() {
    setBusy(true);
    setError(null);
    try {
      const created = await apiFetch<ChatConversationSummary>("/api/chat/conversations", {
        method: "POST",
      });
      setConversationId(created.id);
      setHistory([]);
      setProposal(null);
      setPickerOpen(false);
      setNotice("Empezamos de cero.");
      await loadConversations();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onPickConversation(id: string) {
    setPickerOpen(false);
    if (id === conversationId) return;
    setConversationId(id);
    setProposal(null);
    setLoadingHistory(true);
    await loadHistory(id);
  }

  async function onDeleteConversation(id: string) {
    if (!window.confirm("Se borrará esta conversación y sus mensajes. Lo que ya apuntaste en tu diario no se toca. ¿Seguimos?")) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/chat/conversations/${id}`, { method: "DELETE" });
      const remaining = conversations.filter((c) => c.id !== id);
      setConversations(remaining);
      if (id === conversationId) {
        const next = remaining[0]?.id ?? null;
        setConversationId(next);
        setHistory([]);
        setProposal(null);
        if (next) await loadHistory(next);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  /** Borra los mensajes del servidor. No toca nada de lo que ya se apuntó en el diario. */
  async function onDeleteHistory() {
    if (!window.confirm("Se borrarán todos los mensajes del chat y no se pueden recuperar. Lo que ya apuntaste en tu diario no se toca. ¿Seguimos?")) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/api/chat/history", { method: "DELETE" });
      setHistory([]);
      setConversations([]);
      setConversationId(null);
      setProposal(null);
      setPickerOpen(false);
      setNotice("Historial borrado.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
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
      cancelledRef.current = false;
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        if (cancelledRef.current) {
          chunksRef.current = [];
          return;
        }
        const blob = new Blob(chunksRef.current, { type: mimeType });
        const body = new FormData();
        body.set("audio", blob, "nota.webm");
        // Con `pending` se ve la burbuja de la nota mientras Whisper transcribe: sin ella la
        // pantalla solo mostraba «Pensando…» y parecía que no se había enviado nada.
        void send(body, "Nota de voz enviada…");
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecordingSeconds(0);
      setRecording(true);
      // Si antes falló (permiso denegado y luego concedido), el aviso debe desaparecer.
      setMicUnsupported(false);
    } catch {
      setMicUnsupported(true);
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  }

  function cancelRecording() {
    cancelledRef.current = true;
    mediaRecorderRef.current?.stop();
    setRecording(false);
    setRecordingSeconds(0);
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
      if (decision === "approve") {
        setNotice("Apuntado en tu diario.");
        setShowDiaryLink(true);
      }
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
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void onNewConversation()}
            disabled={sending || busy || loadingHistory}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-full bg-[var(--color-primary)] px-3 text-xs font-semibold text-[var(--color-on-primary)] hover:bg-[var(--color-primary-hover)] disabled:opacity-60"
          >
            <Plus size={14} aria-hidden="true" /> Conversación nueva
          </button>
          <button
            type="button"
            onClick={() => setPickerOpen(true)}
            disabled={sending || busy || conversations.length === 0}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-[var(--color-border-strong)] px-3 text-xs font-semibold disabled:opacity-60"
          >
            <History size={13} aria-hidden="true" /> Anteriores
            {conversations.length > 1 && (
              <span className="text-[var(--color-muted)]">({conversations.length})</span>
            )}
          </button>
          <button
            type="button"
            onClick={() => void onDeleteHistory()}
            disabled={sending || busy || conversations.length === 0}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-[var(--color-border-strong)] px-3 text-xs font-semibold text-[var(--color-muted)] disabled:opacity-60"
          >
            <Trash2 size={13} aria-hidden="true" /> Borrar el historial
          </button>
          {notice && (
            <span role="status" className="self-center text-xs font-semibold text-[var(--color-primary)]">
              {notice}
              {showDiaryLink && (
                <>
                  {" "}
                  <Link href="/log" className="underline">
                    Ver el diario
                  </Link>
                </>
              )}
            </span>
          )}
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
                <Mic
                  size={12}
                  aria-label="Enviado por voz"
                  className="mr-1 inline-block align-[-1px] opacity-70"
                />
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

        {proposal?.scope === "diary" && (
          <DiaryProposalCard
            payload={proposal.payload}
            deciding={deciding}
            onDecide={(decision) => void decideProposal(decision)}
          />
        )}

        {proposal && proposal.scope !== "diary" && (
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
        {recording && (
          <button
            type="button"
            onClick={cancelRecording}
            aria-label="Descartar la nota de voz"
            title="Descartar"
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-control)] border border-[var(--color-border-strong)] text-[var(--color-muted)]"
          >
            <X size={18} aria-hidden="true" />
          </button>
        )}
        <button
          type="button"
          onClick={() => void (recording ? stopRecording() : startRecording())}
          disabled={sending || (!recording && quota?.remaining === 0)}
          aria-label={recording ? "Enviar la nota de voz" : "Grabar una nota de voz"}
          aria-pressed={recording}
          title={recording ? "Enviar la nota de voz" : "Grabar nota de voz"}
          className={`relative inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-[var(--radius-control)] border px-3 text-sm font-semibold transition-colors disabled:opacity-60 ${
            recording
              ? "border-transparent bg-red-600 text-white"
              : "border-[var(--color-border-strong)] bg-[var(--color-surface)] text-[var(--color-primary)] hover:bg-[var(--color-primary-soft)]"
          }`}
        >
          {recording ? (
            <>
              {/* El anillo late mientras graba: es la señal de que el micro está abierto. */}
              <span
                aria-hidden="true"
                className="absolute inset-0 rounded-[var(--radius-control)] bg-red-500/40 motion-safe:animate-[myfood-pulse_1.4s_ease-in-out_infinite]"
              />
              <Square size={16} aria-hidden="true" className="relative fill-current" />
              <span className="relative tabular-nums">{formatDuration(recordingSeconds)}</span>
            </>
          ) : (
            <Mic size={18} aria-hidden="true" />
          )}
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

      <BottomSheet
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title="Conversaciones"
      >
        <ul className="flex flex-col gap-1">
          {conversations.map((c) => (
            <li key={c.id} className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => void onPickConversation(c.id)}
                aria-current={c.id === conversationId ? "true" : undefined}
                className={`min-h-11 flex-1 rounded-[var(--radius-control)] px-3 py-2 text-left text-sm ${
                  c.id === conversationId
                    ? "bg-[var(--color-primary-soft)] font-semibold"
                    : "hover:bg-[var(--color-surface-2)]"
                }`}
              >
                <span className="block truncate">{conversationLabel(c)}</span>
                <span className="block text-xs text-[var(--color-muted)]">
                  {new Date(c.last_message_at).toLocaleDateString("es-ES", {
                    day: "numeric",
                    month: "short",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </button>
              <button
                type="button"
                onClick={() => void onDeleteConversation(c.id)}
                disabled={busy}
                aria-label={`Borrar la conversación «${conversationLabel(c)}»`}
                className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-[var(--radius-control)] text-[var(--color-muted)] hover:bg-[var(--color-surface-2)] disabled:opacity-60"
              >
                <Trash2 size={16} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      </BottomSheet>
    </main>
  );
}
