import { useEffect } from "react";
import { useShell, type PageBack } from "../components/layout/shellContext";

export const APP_NAME = "Nexus";

/** "Library – Nexus"; just "Nexus" when there is no title yet. */
export const formatDocumentTitle = (title: string | null | undefined) =>
  title ? `${title} – ${APP_NAME}` : APP_NAME;

/**
 * Sets `document.title` and tells the shell the page name (phone top bar, route announcement)
 * and an optional back target. Call it once at the top of every page; pass `null` while the
 * real name (story or chapter title) is loading.
 *
 *   usePageTitle("Library");
 *   usePageTitle(story ? displayTitle(story) : null, { back: { to: "/library", label: "Back to Library" } });
 */
export function usePageTitle(title: string | null | undefined, options?: { back?: PageBack }) {
  const shell = useShell();
  const backTo = options?.back?.to;
  const backLabel = options?.back?.label;

  useEffect(() => {
    document.title = formatDocumentTitle(title);
    shell?.setPageMeta({
      title: title ?? null,
      back: backTo && backLabel ? { to: backTo, label: backLabel } : undefined,
    });
  }, [shell, title, backTo, backLabel]);
}
