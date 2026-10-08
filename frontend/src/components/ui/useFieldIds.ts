import { useId } from "react";

/** Stable ids for a control and its hint/error elements. */
export function useFieldIds(id?: string) {
  const generated = useId();
  const controlId = id ?? `f${generated.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  return { controlId, hintId: `${controlId}-hint`, errorId: `${controlId}-error` };
}
