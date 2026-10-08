import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import LibraryPage from "./Library";
import LibrarySwitcher from "../components/layout/LibrarySwitcher";
import { useLibraryContext } from "../context/useLibraryContext";
import { usePageTitle } from "../hooks/usePageTitle";
import { EmptyState, Button } from "../components/ui";

/**
 * `/library` for the active library. `?library=<id>` (old `/library/:id` links) selects that
 * library; `?add=1` opens the add form (top bar Add story). Both are removed from the URL after.
 * The library switcher sits here until D10 moves it into the page.
 */
export default function LibraryRoute() {
  usePageTitle("Library");
  const [params, setParams] = useSearchParams();
  const { activeLibraryId, libraries, isLoading, selectLibrary } = useLibraryContext();
  const requested = Number(params.get("library"));
  const libraryId = Number.isInteger(requested) && requested > 0 ? requested : activeLibraryId;
  const wantsAdd = params.get("add") === "1";

  useEffect(() => {
    if (!params.has("library") && !wantsAdd) return;
    if (Number.isInteger(requested) && requested > 0 && requested !== activeLibraryId) selectLibrary(requested);
    if (wantsAdd && libraryId != null) {
      window.dispatchEvent(new CustomEvent("nexus:add-novel", { detail: { libraryId } }));
    }
    const next = new URLSearchParams(params);
    next.delete("library");
    next.delete("add");
    setParams(next, { replace: true });
  }, [params, requested, wantsAdd, libraryId, activeLibraryId, selectLibrary, setParams]);

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

  return (
    <>
      {libraries.length > 0 && (
        <div className="library-route__switcher">
          <LibrarySwitcher onCreateLibrary={() => window.dispatchEvent(new Event("nexus:create-library"))} />
        </div>
      )}
      <LibraryPage key={libraryId} library_id={libraryId} />
    </>
  );
}
