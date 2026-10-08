import { useEffect, type RefObject } from "react";

let lockCount = 0;
let savedOverflow = "";
let savedPaddingRight = "";

/**
 * While `active`: makes everything outside the overlay inert (not focusable, hidden from
 * assistive tech) and locks page scroll. `ref` points at the overlay's root, which must be
 * a direct child of <body> (overlays render through a portal). Nested overlays work: each
 * one only un-inerts what it changed.
 */
export function useInertBackground(ref: RefObject<HTMLElement | null>, active: boolean) {
  useEffect(() => {
    if (!active) return;
    const overlay = ref.current;
    if (!overlay) return;

    let root: HTMLElement = overlay;
    while (root.parentElement && root.parentElement !== document.body) root = root.parentElement;

    const changed: HTMLElement[] = [];
    for (const child of Array.from(document.body.children) as HTMLElement[]) {
      if (child === root || child.hasAttribute("inert") || child.tagName === "SCRIPT") continue;
      child.setAttribute("inert", "");
      changed.push(child);
    }

    if (lockCount === 0) {
      const scrollbar = window.innerWidth - document.documentElement.clientWidth;
      savedOverflow = document.body.style.overflow;
      savedPaddingRight = document.body.style.paddingRight;
      document.body.style.overflow = "hidden";
      if (scrollbar > 0) document.body.style.paddingRight = `${scrollbar}px`;
    }
    lockCount++;

    return () => {
      changed.forEach((el) => el.removeAttribute("inert"));
      lockCount--;
      if (lockCount === 0) {
        document.body.style.overflow = savedOverflow;
        document.body.style.paddingRight = savedPaddingRight;
      }
    };
  }, [active, ref]);
}
