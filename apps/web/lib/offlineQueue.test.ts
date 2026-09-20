import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import {
  clearQueue,
  flushQueue,
  listQueue,
  retryItem,
  submitOrQueue,
  type QueueItem,
} from "@/lib/offlineQueue";

const USER = "user-1";
const OTHER = "user-2";

async function reset() {
  await clearQueue(USER);
  await clearQueue(OTHER);
}

function foodOpts(userId = USER, label = "Pollo 100 g") {
  return {
    userId,
    kind: "food" as const,
    label,
    payload: { log_date: "2026-09-20", meal_type: "lunch", food_id: "f1", grams: 100 },
  };
}

const networkDown = () => Promise.reject(new TypeError("Failed to fetch"));

beforeEach(reset);

describe("submitOrQueue", () => {
  it("sends directly when the request succeeds and queues nothing", async () => {
    const send = vi.fn().mockResolvedValue({ id: "x" });

    const out = await submitOrQueue(foodOpts(), send);

    expect(out.queued).toBe(false);
    expect(send).toHaveBeenCalledOnce();
    expect(await listQueue(USER)).toHaveLength(0);
  });

  it("sends a client_id and queues the record when the network is down", async () => {
    const send = vi.fn().mockImplementation(networkDown);

    const out = await submitOrQueue(foodOpts(), send);

    expect(out.queued).toBe(true);
    const [item] = await listQueue(USER);
    expect(item.status).toBe("pending");
    expect(item.path).toBe("/api/log/food");
    expect(item.payload.client_id).toBe(item.id);
    expect(JSON.parse(send.mock.calls[0][1]).client_id).toBe(item.id);
  });

  it("queues when the proxy answers 502/503/504 (server unreachable)", async () => {
    const send = vi.fn().mockRejectedValue(new ApiError(502, "UNKNOWN_ERROR", "Error 502"));

    const out = await submitOrQueue(foodOpts(), send);

    expect(out.queued).toBe(true);
  });

  it("does not queue a record the API rejects", async () => {
    const send = vi.fn().mockRejectedValue(new ApiError(422, "VALIDATION_ERROR", "grams"));

    await expect(submitOrQueue(foodOpts(), send)).rejects.toBeInstanceOf(ApiError);
    expect(await listQueue(USER)).toHaveLength(0);
  });

  it("queues without trying when the browser reports it is offline", async () => {
    vi.stubGlobal("navigator", { onLine: false });
    const send = vi.fn();
    try {
      const out = await submitOrQueue(foodOpts(), send);
      expect(out.queued).toBe(true);
      expect(send).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("flushQueue", () => {
  async function queueTwo() {
    await submitOrQueue(foodOpts(USER, "uno"), networkDown);
    await submitOrQueue(
      { userId: USER, kind: "water", label: "250 ml", payload: { log_date: "2026-09-20", ml: 250 } },
      networkDown,
    );
  }

  it("sends the pending records in order and empties the queue", async () => {
    await queueTwo();
    const sent: QueueItem[] = [];

    const res = await flushQueue(USER, async (item) => void sent.push(item));

    expect(res).toMatchObject({ sent: 2, rejected: 0, remaining: 0, needsLogin: false });
    expect(sent.map((i) => i.kind)).toEqual(["food", "water"]);
    expect(await listQueue(USER)).toHaveLength(0);
  });

  it("stops on a network failure and keeps everything that was not sent", async () => {
    await queueTwo();
    const send = vi.fn().mockImplementation(networkDown);

    const res = await flushQueue(USER, send);

    expect(res.sent).toBe(0);
    expect(res.remaining).toBe(2);
    expect(send).toHaveBeenCalledOnce();
  });

  it("keeps a record the API rejects as rejected and continues with the next one", async () => {
    await queueTwo();
    let calls = 0;

    const res = await flushQueue(USER, async () => {
      calls += 1;
      if (calls === 1) throw new ApiError(404, "FOOD_NOT_FOUND", "No existe ese alimento.");
    });

    expect(res).toMatchObject({ sent: 1, rejected: 1, remaining: 0 });
    const left = await listQueue(USER);
    expect(left).toHaveLength(1);
    expect(left[0]).toMatchObject({ status: "rejected", error: "No existe ese alimento." });
  });

  it("does not resend rejected records until the user retries them", async () => {
    await submitOrQueue(foodOpts(), networkDown);
    await flushQueue(USER, async () => {
      throw new ApiError(422, "VALIDATION_ERROR", "mal");
    });
    const send = vi.fn().mockResolvedValue(undefined);

    await flushQueue(USER, send);
    expect(send).not.toHaveBeenCalled();

    const [item] = await listQueue(USER);
    await retryItem(item.id);
    await flushQueue(USER, send);
    expect(send).toHaveBeenCalledOnce();
    expect(await listQueue(USER)).toHaveLength(0);
  });

  it("asks to log in again on 401 without losing the records", async () => {
    await queueTwo();

    const res = await flushQueue(USER, async () => {
      throw new ApiError(401, "UNAUTHENTICATED", "Sesión caducada");
    });

    expect(res.needsLogin).toBe(true);
    expect(res.remaining).toBe(2);
  });

  it("retries later on 429 instead of discarding the record", async () => {
    await queueTwo();

    const res = await flushQueue(USER, async () => {
      throw new ApiError(429, "RATE_LIMITED", "Demasiadas peticiones");
    });

    expect(res).toMatchObject({ sent: 0, rejected: 0, remaining: 2 });
  });

  it("never sends another user's records with this session", async () => {
    await submitOrQueue(foodOpts(OTHER, "ajeno"), networkDown);
    await submitOrQueue(foodOpts(USER, "mío"), networkDown);
    const sent: string[] = [];

    await flushQueue(USER, async (item) => void sent.push(item.label));

    expect(sent).toEqual(["mío"]);
    expect(await listQueue(OTHER)).toHaveLength(1);
  });

  it("shares a single pass between simultaneous calls", async () => {
    await queueTwo();
    const send = vi.fn().mockResolvedValue(undefined);

    const [a, b] = await Promise.all([flushQueue(USER, send), flushQueue(USER, send)]);

    expect(a).toBe(b);
    expect(send).toHaveBeenCalledTimes(2);
  });
});

describe("ordering", () => {
  it("keeps the order of records queued within the same millisecond", async () => {
    const labels = Array.from({ length: 30 }, (_, i) => `registro ${i}`);
    for (const label of labels) await submitOrQueue(foodOpts(USER, label), networkDown);

    const sent: string[] = [];
    await flushQueue(USER, async (item) => void sent.push(item.label));

    expect(sent).toEqual(labels);
  });
});

describe("clearQueue", () => {
  it("only removes the given user's records", async () => {
    await submitOrQueue(foodOpts(USER), networkDown);
    await submitOrQueue(foodOpts(OTHER), networkDown);

    await clearQueue(USER);

    expect(await listQueue(USER)).toHaveLength(0);
    expect(await listQueue(OTHER)).toHaveLength(1);
  });
});
