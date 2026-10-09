import { describe, expect, it, vi } from "vitest";
import { createReadingHeartbeat, type HeartbeatClock } from "./readingHeartbeat";

function fakeClock(start = 1_000_000) {
  const state = { t: start, visible: true };
  const clock: HeartbeatClock = { now: () => state.t, visible: () => state.visible };
  return { state, clock };
}

describe("createReadingHeartbeat", () => {
  it("reports elapsed seconds when the user was active within the last minute", () => {
    const { state, clock } = fakeClock();
    const send = vi.fn(() => Promise.resolve());
    const beat = createReadingHeartbeat(send, clock);
    state.t += 30_000;
    beat.activity();
    state.t += 30_000;
    expect(beat.tick()).toBe(60);
    expect(send).toHaveBeenCalledWith(60, 250);
  });

  it("skips beats when the user has been idle for more than a minute", () => {
    const { state, clock } = fakeClock();
    const send = vi.fn(() => Promise.resolve());
    const beat = createReadingHeartbeat(send, clock);
    beat.activity();
    state.t += 61_000;
    expect(beat.tick()).toBe(0);
    expect(send).not.toHaveBeenCalled();
  });

  it("skips beats while the tab is hidden", () => {
    const { state, clock } = fakeClock();
    const send = vi.fn(() => Promise.resolve());
    const beat = createReadingHeartbeat(send, clock);
    beat.activity();
    state.t += 30_000;
    state.visible = false;
    expect(beat.tick()).toBe(0);
    expect(send).not.toHaveBeenCalled();
  });

  it("caps a single beat at 90 seconds even after a long gap", () => {
    const { state, clock } = fakeClock();
    const send = vi.fn(() => Promise.resolve());
    const beat = createReadingHeartbeat(send, clock);
    state.t += 10 * 60_000;
    beat.activity();
    state.t += 10 * 60_000;
    beat.activity();
    expect(beat.tick()).toBe(90);
    expect(send).toHaveBeenCalledWith(90, 375);
  });

  it("does not count time twice across consecutive beats", () => {
    const { state, clock } = fakeClock();
    const send = vi.fn(() => Promise.resolve());
    const beat = createReadingHeartbeat(send, clock);
    beat.activity();
    state.t += 60_000;
    beat.tick();
    beat.activity();
    state.t += 60_000;
    expect(beat.tick()).toBe(60);
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("swallows failed sends so offline beats are simply dropped", async () => {
    const { state, clock } = fakeClock();
    const beat = createReadingHeartbeat(() => Promise.reject(new Error("offline")), clock);
    beat.activity();
    state.t += 60_000;
    expect(() => beat.tick()).not.toThrow();
    await Promise.resolve();
  });
});
