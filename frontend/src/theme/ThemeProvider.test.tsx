import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "./ThemeProvider";
import { useTheme } from "./useTheme";
import { THEME_STORAGE_KEY } from "./themeStore";

type Listener = (event: MediaQueryListEvent) => void;
let listeners: Listener[] = [];
let systemDark = false;

function mockMatchMedia() {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: systemDark,
    media: query,
    addEventListener: (_: string, l: Listener) => listeners.push(l),
    removeEventListener: (_: string, l: Listener) => (listeners = listeners.filter((x) => x !== l)),
  })) as unknown as typeof window.matchMedia;
}

function Probe() {
  const { preference, theme, setPreference } = useTheme();
  return (
    <div>
      <span data-testid="pref">{preference}</span>
      <span data-testid="theme">{theme}</span>
      <button onClick={() => setPreference("dark")}>dark</button>
      <button onClick={() => setPreference("system")}>system</button>
    </div>
  );
}

describe("ThemeProvider", () => {
  beforeEach(() => {
    listeners = [];
    systemDark = false;
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    mockMatchMedia();
  });
  afterEach(() => localStorage.clear());

  it("follows the OS preference by default and reacts to changes", () => {
    systemDark = true;
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId("pref")).toHaveTextContent("system");
    expect(document.documentElement.dataset.theme).toBe("dark");
    act(() => listeners.forEach((l) => l({ matches: false } as MediaQueryListEvent)));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe("#faf8f4");
  });

  it("persists a manual choice and restores it", () => {
    const { unmount } = render(<ThemeProvider><Probe /></ThemeProvider>);
    act(() => screen.getByText("dark").click());
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    unmount();
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId("pref")).toHaveTextContent("dark");
    // OS changes do not override a manual choice
    act(() => listeners.forEach((l) => l({ matches: false } as MediaQueryListEvent)));
    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  });

  it("going back to system clears the stored value", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    render(<ThemeProvider><Probe /></ThemeProvider>);
    act(() => screen.getByText("system").click());
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    expect(screen.getByTestId("theme")).toHaveTextContent("light");
  });
});
