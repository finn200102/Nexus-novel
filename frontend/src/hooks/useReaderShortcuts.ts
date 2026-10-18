import { useEffect, useRef } from "react";

export interface ReaderShortcutHandlers {
  /** Next page (paged) or next chapter (scroll). */
  next: () => void;
  previous: () => void;
  bookmark: () => void;
  chapters: () => void;
  textSettings: () => void;
  smaller: () => void;
  larger: () => void;
  help: () => void;
}

export const READER_SHORTCUTS: { keys: string[]; action: string; singleKey: boolean }[] = [
  { keys: ["→", "J"], action: "Next page, or next chapter in scroll mode", singleKey: true },
  { keys: ["←", "K"], action: "Previous page, or previous chapter in scroll mode", singleKey: true },
  { keys: ["Space", "Shift + Space"], action: "Scroll down or up one screen", singleKey: false },
  { keys: ["C"], action: "Open chapters", singleKey: true },
  { keys: ["A"], action: "Open text settings", singleKey: true },
  { keys: ["B"], action: "Bookmark this place", singleKey: true },
  { keys: ["[", "]"], action: "Smaller or larger text", singleKey: true },
  { keys: ["?"], action: "Show keyboard shortcuts", singleKey: true },
  { keys: ["Esc"], action: "Close the open panel", singleKey: false },
];

/** Focus is in a field, an open menu/dialog or a radio group: keys belong to that control. */
export const isShortcutBlocked = (target: EventTarget | null) => {
  if (!(target instanceof HTMLElement)) return false;
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  if (target.isContentEditable) return true;
  return target.closest("[role='dialog'], [role='menu'], [role='radiogroup'], [role='listbox'], [contenteditable='true']") !== null;
};

/**
 * Reader keyboard shortcuts. Arrow keys always work; single-character keys
 * (J K C A B [ ] ?) only while `enabled` (WCAG 2.1.4). Nothing fires while focus
 * is in a text field, menu, dialog or radio group, or with Ctrl/Alt/Meta held.
 */
export function useReaderShortcuts(handlers: ReaderShortcutHandlers, enabled: boolean) {
  const ref = useRef(handlers);
  ref.current = handlers;

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      if (document.querySelector(".ui-modal-layer")) return;
      if (isShortcutBlocked(event.target)) return;
      const h = ref.current;
      if (event.key === "ArrowRight") { event.preventDefault(); h.next(); return; }
      if (event.key === "ArrowLeft") { event.preventDefault(); h.previous(); return; }
      if (!enabled) return;
      const action: Record<string, () => void> = {
        j: h.next,
        k: h.previous,
        b: h.bookmark,
        c: h.chapters,
        a: h.textSettings,
        "[": h.smaller,
        "]": h.larger,
        "?": h.help,
      };
      const run = action[event.key.length === 1 ? event.key.toLowerCase() : ""];
      if (!run) return;
      event.preventDefault();
      run();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled]);
}
