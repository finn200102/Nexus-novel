import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAudioMediaSession } from "./useAudioMediaSession";

afterEach(() => vi.unstubAllGlobals());

function sessionFixture() {
  const handlers = new Map<string, MediaSessionActionHandler | null>();
  const session = { metadata: null, playbackState: "none", setActionHandler: vi.fn((action, handler) => handlers.set(action, handler)) };
  vi.stubGlobal("navigator", { mediaSession: session });
  vi.stubGlobal("MediaMetadata", class { constructor(public value: unknown) {} });
  return { session, handlers };
}

describe("device audio controls", () => {
  it("uses current callbacks and releases private metadata when the player closes", () => {
    const { session, handlers } = sessionFixture();
    const controls = { active: true, playing: true, title: "Private story", onPlay: vi.fn(), onPause: vi.fn(), onStop: vi.fn(), onSeek: vi.fn() };
    const { rerender, unmount } = renderHook(props => useAudioMediaSession(props), { initialProps: controls });
    expect(session.playbackState).toBe("playing");
    handlers.get("pause")!({ action: "pause" });
    expect(controls.onPause).toHaveBeenCalledOnce();
    handlers.get("seekforward")!({ action: "seekforward", seekOffset: 30 });
    handlers.get("seekto")!({ action: "seekto", seekTime: 42 });
    expect(controls.onSeek.mock.calls).toEqual([[30, true], [42, false]]);
    const onPlay = vi.fn();
    rerender({ ...controls, onPlay, playing: false });
    handlers.get("play")!({ action: "play" });
    expect(onPlay).toHaveBeenCalledOnce();
    expect(session.playbackState).toBe("paused");
    unmount();
    expect(session.metadata).toBeNull();
    expect(session.playbackState).toBe("none");
    expect([...handlers.values()].every(value => value === null)).toBe(true);
  });

  it("does not advertise seeking for browser voices", () => {
    const { handlers } = sessionFixture();
    renderHook(() => useAudioMediaSession({ active: true, playing: false, title: "Chapter", onPlay: vi.fn(), onPause: vi.fn(), onStop: vi.fn() }));
    expect(handlers.has("seekto")).toBe(false);
    expect(handlers.has("play")).toBe(true);
  });

  it("works when a browser has no media controls or rejects an action", () => {
    vi.stubGlobal("navigator", {});
    const controls = { active: true, playing: false, title: "Chapter", onPlay: vi.fn(), onPause: vi.fn(), onStop: vi.fn() };
    const { unmount } = renderHook(() => useAudioMediaSession(controls));
    unmount();
    const { session } = sessionFixture();
    session.setActionHandler.mockImplementation(() => { throw new Error("unsupported"); });
    expect(() => renderHook(() => useAudioMediaSession(controls)).unmount()).not.toThrow();
  });
});
