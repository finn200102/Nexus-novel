import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useReaderAssetsReady, waitForReaderImages } from "./useReaderAssetsReady";

vi.mock("../components/reader/readerFonts", () => ({}));
afterEach(() => { vi.useRealTimers(); });
function fixture() {
  const container = document.createElement("div");
  container.innerHTML = '<section data-block-id="art"><img alt="Map"><img alt="Portrait"></section>';
  const images = Array.from(container.querySelectorAll("img"));
  for (const image of images) Object.defineProperty(image, "complete", { configurable: true, value: false });
  return { container, images };
}

describe("reader asset readiness", () => {
  it("waits for all image dimensions, treating broken images as settled", async () => {
    const { container, images } = fixture(), controller = new AbortController(), settled = vi.fn();
    const waiting = waitForReaderImages(container, controller.signal).then(settled);
    images[0].dispatchEvent(new Event("load")); await Promise.resolve();
    expect(settled).not.toHaveBeenCalled();
    images[1].dispatchEvent(new Event("error")); await waiting;
    expect(settled).toHaveBeenCalledTimes(1);
  });
  it("bounds image waits and removes pending listeners on timeout or cancellation", async () => {
    vi.useFakeTimers();
    const { container, images } = fixture(), controller = new AbortController();
    const removed = vi.spyOn(images[0], "removeEventListener");
    const waiting = waitForReaderImages(container, controller.signal, 100);
    await vi.advanceTimersByTimeAsync(100); await waiting;
    expect(removed).toHaveBeenCalledWith("load", expect.any(Function));
    expect(removed).toHaveBeenCalledWith("error", expect.any(Function));
    const cancelled = new AbortController(), next = waitForReaderImages(container, cancelled.signal);
    cancelled.abort(); await next;
    expect(vi.getTimerCount()).toBe(0);
  });
  it("ignores settled assets and images outside story blocks", async () => {
    const container = document.createElement("div"); container.innerHTML = '<img alt="Toolbar">';
    Object.defineProperty(container.querySelector("img"), "complete", { value: false });
    await waitForReaderImages(container, new AbortController().signal);
    const ready = fixture(); for (const image of ready.images) Object.defineProperty(image, "complete", { value: true });
    await waitForReaderImages(ready.container, new AbortController().signal);
  });
  it("cannot unlock a new rendition with the prior rendition's completion", async () => {
    const first = fixture(), second = fixture(), ref = { current: first.container };
    const view = renderHook(({ key }) => useReaderAssetsReady(ref, key), { initialProps: { key: "first" } });
    expect(view.result.current).toBe(false);
    ref.current = second.container; view.rerender({ key: "second" });
    await act(async () => { first.images.forEach(image => image.dispatchEvent(new Event("load"))); });
    expect(view.result.current).toBe(false);
    await act(async () => { second.images.forEach(image => image.dispatchEvent(new Event("load"))); });
    await waitFor(() => expect(view.result.current).toBe(true));
  });
  it("allows reading after a stalled font deadline and cancels timers on unmount", async () => {
    vi.useFakeTimers();
    const prior = Object.getOwnPropertyDescriptor(document, "fonts");
    Object.defineProperty(document, "fonts", { configurable: true, value: { ready: new Promise(() => {}) } });
    try {
      const { container } = fixture(), ref = { current: container };
      const view = renderHook(() => useReaderAssetsReady(ref, "stalled-font"));
      expect(view.result.current).toBe(false);
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(view.result.current).toBe(true);
      view.unmount(); expect(vi.getTimerCount()).toBe(0);
      const cancelled = renderHook(() => useReaderAssetsReady(ref, "cancelled-font"));
      cancelled.unmount(); await act(async () => { await Promise.resolve(); });
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      if (prior) Object.defineProperty(document, "fonts", prior);
      else Reflect.deleteProperty(document, "fonts");
    }
  });
});
