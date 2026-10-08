import { createContext, useContext } from "react";

/** Optional back target shown in the phone top bar (e.g. Story → Library). */
export interface PageBack {
  to: string;
  /** Accessible name, e.g. "Back to Library". */
  label: string;
}

export interface PageMeta {
  /** Short page name without " – Nexus"; null while loading. */
  title: string | null;
  back?: PageBack;
}

export interface ShellContextValue {
  setPageMeta: (meta: PageMeta) => void;
}

/** Provided by the app shell (`Layout`) and the reader layout. Absent in tests and auth pages. */
export const ShellContext = createContext<ShellContextValue | null>(null);

export const useShell = () => useContext(ShellContext);
