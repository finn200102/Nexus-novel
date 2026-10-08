import { createContext } from "react";
import type { ResolvedTheme, ThemePreference } from "./themeStore";

export interface ThemeContextValue {
  /** What the user chose. */
  preference: ThemePreference;
  /** What is applied right now (system resolved through the OS setting). */
  theme: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);
