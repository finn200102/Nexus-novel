import { useEffect } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import LibraryPage from "./Library";
import { openAddStory } from "../components/add/addStoryEvents";
import { useLibraryContext } from "../context/useLibraryContext";
import { usePageTitle } from "../hooks/usePageTitle";
import { EmptyState, Button } from "../components/ui";

interface StoryHandoff {
  storyLink?: string;
}

/**
 * `/library` for the active library. `?library=<id>` (old `/library/:id` links) selects that
 * library; `?add=1` (old links) opens the Add story sheet. Both are removed from the URL after.
 * The page heading itself is the library switcher (`LibraryTitleMenu`).
 */
export default function LibraryRoute() {
  usePageTitle("Library");
  const [params, setParams] = useSearchParams();
  const { activeLibraryId, isLoading, selectLibrary } = useLibraryContext();
  const requested = Number(params.get("library"));
  const libraryId = Number.isInteger(requested) && requested > 0 ? requested : activeLibraryId;
  const wantsAdd = params.get("add") === "1";
  const location = useLocation();
  const handoff = (location.state as StoryHandoff | null)?.storyLink ?? null;

  useEffect(() => {
    if (!params.has("library") && !wantsAdd) return;
    if (Number.isInteger(requested) && requested > 0 && requested !== activeLibraryId) selectLibrary(requested);
    if (wantsAdd && libraryId != null) {
      openAddStory({ libraryId, url: handoff ?? undefined });
    }
    const next = new URLSearchParams(params);
    next.delete("library");
    next.delete("add");
    setParams(next, { replace: true });
  }, [params, requested, wantsAdd, libraryId, activeLibraryId, selectLibrary, setParams, handoff]);

  if (libraryId == null) {
    if (isLoading) return <p role="status">Loading your library…</p>;
    return (
      <EmptyState
        title="No library yet"
        description="Create a library to start adding stories."
        action={<Button variant="primary" onClick={() => window.dispatchEvent(new Event("nexus:create-library"))}>Create library</Button>}
      />
    );
  }

  return <LibraryPage key={libraryId} library_id={libraryId} />;
}
