import { useEffect, useRef, useState, type FormEvent } from "react";
import axios from "axios";
import { Button, Select, Sheet, Tabs, TextArea } from "../ui";
import { useLibraryContext } from "../../context/useLibraryContext";
import { useToast } from "../../context/useToast";
import { novelService } from "../../services/novelService";
import { ImportJobsPanel } from "./ImportJobsPanel";
import { notifyStoryAdded, parseLinks, type OpenAddStoryDetail } from "./addStoryEvents";
import "../../styles/add-story.css";

interface AddStorySheetProps {
  open: boolean;
  onClose: () => void;
  /** What the opener asked for (prefilled link, library, tab). */
  request: OpenAddStoryDetail;
}

type Tab = "link" | "import";

/**
 * The one Add story flow (proposal §4.2): paste one or more links, or import a list / EPUBs.
 * Opened from the top bar, Home, Discover and Library via `openAddStory()`; mounted once in Layout.
 */
export function AddStorySheet({ open, onClose, request }: AddStorySheetProps) {
  const { libraries, activeLibraryId } = useLibraryContext();
  const { addToast } = useToast();
  const [tab, setTab] = useState<Tab>("link");
  const [libraryId, setLibraryId] = useState<number | null>(null);
  const [links, setLinks] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const linkRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!open) return;
    setTab(request.tab ?? "link");
    setLibraryId(request.libraryId ?? activeLibraryId ?? libraries[0]?.id ?? null);
    setLinks(request.url ?? "");
    setError(null);
    // Only when the sheet opens; later library changes keep the user's choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, request]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const urls = parseLinks(links);
    if (!libraryId) {
      setError("Choose a library first.");
      return;
    }
    if (urls.length === 0) {
      setError("Paste a link to a story.");
      linkRef.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (urls.length === 1) await novelService.addNovel(libraryId, urls[0]);
      else await novelService.addNovels(libraryId, urls);
      addToast(urls.length === 1 ? "Story added. Chapters are downloading." : `${urls.length} stories added. Chapters are downloading.`, "success");
      notifyStoryAdded(libraryId);
      setLinks("");
      onClose();
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : undefined;
      if (detail === "Novel already exists") {
        addToast("This story is already in your library.", "info");
        notifyStoryAdded(libraryId);
        onClose();
      } else {
        setError(typeof detail === "string" ? detail : "We couldn't add this story. Check the link and try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  const libraryPicker =
    libraries.length > 1 ? (
      <Select
        label="Add to library"
        value={libraryId != null ? String(libraryId) : ""}
        onChange={(event) => setLibraryId(Number(event.target.value))}
        options={libraries.map((library) => ({ value: String(library.id), label: library.name }))}
      />
    ) : null;

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Add story"
      initialFocus={linkRef}
      className="add-story-sheet"
      footer={
        tab === "link" ? (
          <Button type="submit" form="add-story-form" variant="primary" block loading={busy} disabled={busy}>
            Add to library
          </Button>
        ) : undefined
      }
    >
      <div className="add-story">
        <Tabs<Tab>
          label="How to add"
          value={tab}
          onChange={setTab}
          items={[
            {
              value: "link",
              label: "Paste a link",
              panel: (
                <form id="add-story-form" className="add-story__form" onSubmit={submit} noValidate>
                  {libraryPicker}
                  <TextArea
                    ref={linkRef}
                    label="Story link"
                    hint="Royal Road, AO3, FanFiction.Net, SpaceBattles and more. Paste several links on separate lines to add them all."
                    placeholder="https://www.royalroad.com/fiction/…"
                    rows={3}
                    value={links}
                    error={error ?? undefined}
                    onChange={(event) => setLinks(event.target.value)}
                    disabled={busy}
                  />
                </form>
              ),
            },
            {
              value: "import",
              label: "Import",
              panel: (
                <div className="add-story__form">
                  {libraryPicker}
                  <ImportJobsPanel libraryId={libraryId} onError={(message) => addToast(message, "error")} />
                </div>
              ),
            },
          ]}
        />
      </div>
    </Sheet>
  );
}

export default AddStorySheet;
