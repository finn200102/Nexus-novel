import { useCallback, useRef, type KeyboardEvent } from "react";

/**
 * Keyboard model of a radio group (WAI-ARIA APG): one tab stop on the checked option,
 * arrow keys move and select (wrapping), Home/End jump. Disabled options are skipped.
 */
export function useRovingRadio<T extends string>(
  values: readonly T[],
  value: T | undefined,
  onChange: (value: T) => void,
  isDisabled: (value: T) => boolean = () => false,
) {
  const refs = useRef(new Map<T, HTMLElement>());

  const register = useCallback(
    (v: T) => (node: HTMLElement | null) => {
      if (node) refs.current.set(v, node);
      else refs.current.delete(v);
    },
    [],
  );

  const enabled = values.filter((v) => !isDisabled(v));
  const tabStop = value !== undefined && enabled.includes(value) ? value : enabled[0];

  const onKeyDown = (event: KeyboardEvent) => {
    if (!enabled.length) return;
    const current = enabled.indexOf((value ?? enabled[0]) as T);
    let next: number | null = null;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        next = (current + 1) % enabled.length;
        break;
      case "ArrowLeft":
      case "ArrowUp":
        next = (current - 1 + enabled.length) % enabled.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = enabled.length - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    const target = enabled[next];
    onChange(target);
    refs.current.get(target)?.focus();
  };

  return { register, tabStop, onKeyDown };
}
