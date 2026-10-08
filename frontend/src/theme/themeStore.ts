export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

/** localStorage key; also read by the inline script in index.html before first paint. */
export const THEME_STORAGE_KEY = "nexus-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";
/** Values for <meta name="theme-color"> (= --bg of each theme). */
export const THEME_COLORS: Record<ResolvedTheme, string> = { light: "#faf8f4", dark: "#121315" };

export function readPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

export function writePreference(preference: ThemePreference): void {
  try {
    if (preference === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // storage unavailable (private mode): the choice lasts for this page view only
  }
}

export function systemTheme(): ResolvedTheme {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  return preference === "system" ? systemTheme() : preference;
}

/** Sets data-theme on <html> and the browser chrome colour. */
export function applyTheme(theme: ResolvedTheme, doc: Document = document): void {
  doc.documentElement.setAttribute("data-theme", theme);
  let meta = doc.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (!meta) {
    meta = doc.createElement("meta");
    meta.name = "theme-color";
    doc.head.appendChild(meta);
  }
  meta.content = THEME_COLORS[theme];
}

export function subscribeSystemTheme(onChange: (theme: ResolvedTheme) => void): () => void {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const mql = window.matchMedia(DARK_QUERY);
  const handler = (event: MediaQueryListEvent) => onChange(event.matches ? "dark" : "light");
  mql.addEventListener("change", handler);
  return () => mql.removeEventListener("change", handler);
}
