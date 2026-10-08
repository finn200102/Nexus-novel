import { useEffect, type RefObject } from "react";

const FOCUSABLE = [
  "a[href]",
  "area[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "iframe",
  "audio[controls]",
  "video[controls]",
  "[contenteditable]:not([contenteditable='false'])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

/** Focusable, visible descendants in DOM order. */
export function getFocusable(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => !el.hasAttribute("inert") && !el.closest("[inert]") && el.getAttribute("aria-hidden") !== "true",
  );
}

export interface FocusTrapOptions {
  /** Element to focus on open; default: first focusable, else the container. */
  initialFocus?: RefObject<HTMLElement | null>;
  /** Return focus to the previously focused element on close (default true). */
  restoreFocus?: boolean;
}

/**
 * While `active`: moves focus into `ref`, keeps Tab / Shift+Tab inside it, and on
 * deactivation returns focus to the element that had it before.
 */
export function useFocusTrap(ref: RefObject<HTMLElement | null>, active: boolean, options: FocusTrapOptions = {}) {
  const { initialFocus, restoreFocus = true } = options;

  useEffect(() => {
    if (!active) return;
    const container = ref.current;
    if (!container) return;
    const previous = document.activeElement as HTMLElement | null;

    const target = initialFocus?.current ?? getFocusable(container)[0] ?? container;
    if (target === container && !container.hasAttribute("tabindex")) container.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const items = getFocusable(container);
      if (!items.length) {
        event.preventDefault();
        container.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement;
      if (event.shiftKey && (current === first || !container.contains(current))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (current === last || !container.contains(current))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);

    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      if (restoreFocus && previous && typeof previous.focus === "function" && previous.isConnected) {
        previous.focus({ preventScroll: true });
      }
    };
    // initialFocus is a ref; reading .current at activation time is intended.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, ref, restoreFocus]);
}
