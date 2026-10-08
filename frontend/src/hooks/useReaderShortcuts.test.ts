import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReaderShortcutHandlers, useReaderShortcuts } from "./useReaderShortcuts";

const handlers = (): ReaderShortcutHandlers => ({
  next: vi.fn(), previous: vi.fn(), bookmark: vi.fn(), chapters: vi.fn(),
  textSettings: vi.fn(), smaller: vi.fn(), larger: vi.fn(), help: vi.fn(),
});

const press = (key: string, target: EventTarget = window, init: KeyboardEventInit = {}) =>
  target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }));

describe("useReaderShortcuts", () => {
  it("maps single keys and arrows to actions", () => {
    const h = handlers();
    renderHook(() => useReaderShortcuts(h, true));
    press("j"); press("K"); press("b"); press("c"); press("a"); press("["); press("]"); press("?");
    press("ArrowRight"); press("ArrowLeft");
    expect(h.next).toHaveBeenCalledTimes(2);
    expect(h.previous).toHaveBeenCalledTimes(2);
    for (const fn of [h.bookmark, h.chapters, h.textSettings, h.smaller, h.larger, h.help]) expect(fn).toHaveBeenCalledTimes(1);
  });

  it("does nothing for J/K/B/[ ] when single-key shortcuts are off", () => {
    const h = handlers();
    renderHook(() => useReaderShortcuts(h, false));
    for (const key of ["j", "k", "b", "[", "]", "c", "a", "?"]) press(key);
    expect(Object.values(h).every((fn) => (fn as ReturnType<typeof vi.fn>).mock.calls.length === 0)).toBe(true);
    press("ArrowRight");
    expect(h.next).toHaveBeenCalledTimes(1);
  });

  it("never fires while typing in a field or inside a dialog", () => {
    const h = handlers();
    renderHook(() => useReaderShortcuts(h, true));
    const input = document.createElement("input");
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    const button = document.createElement("button");
    dialog.appendChild(button);
    document.body.append(input, dialog);
    press("j", input); press("b", input); press("ArrowRight", input);
    press("j", button);
    expect(h.next).not.toHaveBeenCalled();
    expect(h.bookmark).not.toHaveBeenCalled();
    input.remove(); dialog.remove();
  });

  it("ignores keys with modifiers", () => {
    const h = handlers();
    renderHook(() => useReaderShortcuts(h, true));
    press("b", window, { metaKey: true });
    press("j", window, { ctrlKey: true });
    expect(h.bookmark).not.toHaveBeenCalled();
    expect(h.next).not.toHaveBeenCalled();
  });
});
