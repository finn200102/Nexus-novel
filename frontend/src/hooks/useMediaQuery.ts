import { useEffect, useState } from "react";

const query = (q: string) =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(q) : null;

/** True while the media query matches. Without matchMedia (tests) it returns `fallback`. */
export function useMediaQuery(q: string, fallback = true) {
  const [matches, setMatches] = useState(() => query(q)?.matches ?? fallback);
  useEffect(() => {
    const mql = query(q);
    if (!mql) return;
    const update = () => setMatches(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, [q]);
  return matches;
}
