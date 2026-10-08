import { useEffect, type RefObject } from "react";

/** Calls `onDismiss` on outside pointer-down or Escape while `active`. */
export function useDismiss(
  refs: RefObject<HTMLElement | null>[],
  active: boolean,
  onDismiss: (reason: "outside" | "escape") => void,
) {
  useEffect(() => {
    if (!active) return;
    const onPointer = (event: PointerEvent | MouseEvent) => {
      const target = event.target as Node;
      if (refs.some((ref) => ref.current?.contains(target))) return;
      onDismiss("outside");
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onDismiss("escape");
      }
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [active, onDismiss, refs]);
}
