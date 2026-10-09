/**
 * Reading-time heartbeat. Every minute the reader reports the seconds since the
 * last beat, but only while the tab is visible and the user scrolled or paged
 * within the last minute. The server clamps the value again (90 s per call).
 */
export const HEARTBEAT_INTERVAL_MS = 60_000;
export const IDLE_CUTOFF_MS = 60_000;
export const MAX_SECONDS_PER_BEAT = 90;
export const WORDS_PER_MINUTE = 250;

export interface HeartbeatClock {
  now: () => number;
  visible: () => boolean;
}

const browserClock: HeartbeatClock = {
  now: () => Date.now(),
  visible: () => typeof document === "undefined" || document.visibilityState === "visible",
};

export interface ReadingHeartbeat {
  /** Call on scroll, paging, or key/pointer input. */
  activity: () => void;
  /** Call once per interval. Returns the seconds reported (0 when skipped). */
  tick: () => number;
}

/**
 * Creates a heartbeat. `send` errors are swallowed: a beat lost offline is simply
 * not counted, which keeps the numbers conservative.
 */
export function createReadingHeartbeat(
  send: (seconds: number, words: number) => Promise<unknown>,
  clock: HeartbeatClock = browserClock,
): ReadingHeartbeat {
  let lastActivity = Number.NEGATIVE_INFINITY;
  let lastTick = clock.now();
  return {
    activity() {
      lastActivity = clock.now();
    },
    tick() {
      const now = clock.now();
      const elapsed = Math.min(MAX_SECONDS_PER_BEAT, Math.max(0, Math.round((now - lastTick) / 1000)));
      lastTick = now;
      const active = clock.visible() && now - lastActivity <= IDLE_CUTOFF_MS;
      if (!active || elapsed === 0) return 0;
      const words = Math.round((elapsed * WORDS_PER_MINUTE) / 60);
      send(elapsed, words).catch(() => undefined);
      return elapsed;
    },
  };
}
