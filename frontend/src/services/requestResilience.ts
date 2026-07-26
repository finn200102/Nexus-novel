import { useEffect, useRef } from "react";
import { isRequestCancelled } from "./apiClient";

type Operation<T> = () => Promise<T>;

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const retryable = (error: unknown) => {
  if (isRequestCancelled(error)) return false;
  const response = (error as { response?: { status?: number } }).response;
  const status = response?.status;
  return !status || status === 408 || status === 429 || status >= 500;
};

/** Deduplicates refreshes and applies one bounded retry to transient reads. */
export class RequestCoordinator {
  private inFlight = new Map<string, Promise<unknown>>();

  run<T>(key: string, operation: Operation<T>, retries = 1): Promise<T> {
    const existing = this.inFlight.get(key);
    if (existing) return existing as Promise<T>;

    const request = (async () => {
      let attempt = 0;
      while (true) {
        try {
          return await operation();
        } catch (error) {
          if (attempt >= retries || !retryable(error)) throw error;
          attempt += 1;
          await wait(250 * 2 ** (attempt - 1));
        }
      }
    })();
    this.inFlight.set(key, request);
    void request.then(
      () => this.inFlight.delete(key),
      () => this.inFlight.delete(key)
    );
    return request;
  }
}

type PollOptions = {
  activeMs?: number;
  visibleIdleMs?: number;
  hiddenMs?: number;
};

/** Polls without overlap, slows down when idle/hidden, and stops on unmount. */
export const useAdaptivePolling = (
  callback: () => void | Promise<void>,
  enabled: boolean,
  { activeMs = 3000, visibleIdleMs = 15000, hiddenMs = 30000 }: PollOptions = {}
) => {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (!enabled) return undefined;
    let stopped = false;
    let timer: number | undefined;
    let running = false;

    const schedule = () => {
      if (stopped) return;
      const delay = document.hidden ? hiddenMs : document.hasFocus() ? activeMs : visibleIdleMs;
      timer = window.setTimeout(async () => {
        if (stopped) return;
        if (!running) {
          running = true;
          try { await callbackRef.current(); } finally { running = false; }
        }
        schedule();
      }, delay);
    };
    const reschedule = () => {
      if (timer) window.clearTimeout(timer);
      schedule();
    };

    document.addEventListener("visibilitychange", reschedule);
    window.addEventListener("focus", reschedule);
    window.addEventListener("blur", reschedule);
    schedule();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", reschedule);
      window.removeEventListener("focus", reschedule);
      window.removeEventListener("blur", reschedule);
    };
  }, [activeMs, enabled, hiddenMs, visibleIdleMs]);
};
