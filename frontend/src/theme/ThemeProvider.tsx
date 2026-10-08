import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ThemeContext } from "./themeContext";
import {
  applyTheme,
  readPreference,
  resolveTheme,
  subscribeSystemTheme,
  writePreference,
  type ResolvedTheme,
  type ThemePreference,
} from "./themeStore";

/**
 * App theme: `system | light | dark`, persisted in localStorage. The inline script in
 * index.html applies the same logic before first paint, so there is no flash.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);
  const [systemResolved, setSystemResolved] = useState<ResolvedTheme>(() => resolveTheme("system"));
  const theme: ResolvedTheme = preference === "system" ? systemResolved : preference;

  useEffect(() => subscribeSystemTheme(setSystemResolved), []);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Keep several open tabs in sync.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === "nexus-theme") setPreferenceState(readPreference());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setPreference = useCallback((next: ThemePreference) => {
    writePreference(next);
    setPreferenceState(next);
  }, []);

  const value = useMemo(() => ({ preference, theme, setPreference }), [preference, theme, setPreference]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
