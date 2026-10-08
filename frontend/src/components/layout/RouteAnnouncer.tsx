import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

const FIELD = "input, select, textarea, [contenteditable='true']";

/**
 * After a route (pathname) change: move focus to the page H1 inside `main#main` (falls back to
 * `main`) and announce the new document title in a polite live region. Not on the first load,
 * and not when focus sits in a form field in the page (filters that update the URL).
 */
export function RouteAnnouncer() {
  const { pathname } = useLocation();
  const [message, setMessage] = useState("");
  const previous = useRef(pathname);

  useEffect(() => {
    // Compare paths rather than counting runs: StrictMode re-runs effects on mount.
    if (previous.current === pathname) return;
    previous.current = pathname;
    const main = document.getElementById("main");
    const active = document.activeElement;
    if (main && active && main.contains(active) && active.matches(FIELD)) return;

    let tries = 0;
    let timer = 0;
    const settle = () => {
      const h1 = document.querySelector<HTMLElement>("#main h1");
      if (!h1 && tries < 30) {
        tries += 1;
        timer = window.setTimeout(settle, 50);
        return;
      }
      const target = h1 ?? document.getElementById("main");
      if (target) {
        if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
        target.focus();
      }
      setMessage("");
      window.setTimeout(() => setMessage(document.title), 30);
    };
    timer = window.setTimeout(settle, 0);
    return () => window.clearTimeout(timer);
  }, [pathname]);

  return (
    <div className="visually-hidden" aria-live="polite" aria-atomic="true" data-testid="route-announcer">
      {message}
    </div>
  );
}
