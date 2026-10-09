import { useRef, useState, type FormEvent } from "react";
import { ChevronDown } from "lucide-react";
import { Button, Dialog, Input, Menu, type MenuItem } from "../ui";
import { useLibraryContext } from "../../context/useLibraryContext";
import { useToast } from "../../context/useToast";
import { getUserFacingError } from "../../services/apiClient";

interface LibraryTitleMenuProps {
  libraryId: number;
  name: string;
}

/**
 * The Library page heading is the library switcher: the title opens a menu to switch library
 * and to create, rename or delete one (owner feedback after D10).
 */
export function LibraryTitleMenu({ libraryId, name }: LibraryTitleMenuProps) {
  const { libraries, selectLibrary, renameLibrary, deleteLibrary } = useLibraryContext();
  const { addToast } = useToast();
  const [dialog, setDialog] = useState<"rename" | "delete" | null>(null);
  const [draft, setDraft] = useState(name);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const items: MenuItem[] = [
    ...libraries.map<MenuItem>((library) => ({
      label: library.name,
      hint: library.id === libraryId ? "Current" : undefined,
      onSelect: () => selectLibrary(library.id),
    })),
    { type: "separator" },
    { label: "New library…", onSelect: () => window.dispatchEvent(new Event("nexus:create-library")) },
    {
      label: "Rename library…",
      onSelect: () => {
        setDraft(name);
        setDialog("rename");
      },
    },
    { label: "Delete library…", danger: true, onSelect: () => setDialog("delete") },
  ];

  const rename = async (event: FormEvent) => {
    event.preventDefault();
    const next = draft.trim();
    if (!next || next === name) {
      setDialog(null);
      return;
    }
    setBusy(true);
    try {
      await renameLibrary(libraryId, next);
      setDialog(null);
    } catch (error) {
      addToast(getUserFacingError(error, "Could not rename the library."), "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await deleteLibrary(libraryId);
      setDialog(null);
      addToast(`Deleted “${name}”.`, "success");
    } catch (error) {
      addToast(getUserFacingError(error, "Could not delete the library."), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Menu
        items={items}
        trigger={(props) => (
          <button {...props} type="button" className="library-title" aria-label={`${name}, switch or manage libraries`}>
            <span className="library-title__name">{name}</span>
            <ChevronDown aria-hidden="true" className="library-title__chevron" />
          </button>
        )}
      />
      <Dialog
        open={dialog === "rename"}
        onClose={() => setDialog(null)}
        title="Rename library"
        initialFocus={inputRef}
        actions={
          <>
            <Button variant="ghost" onClick={() => setDialog(null)}>Cancel</Button>
            <Button type="submit" form="rename-library-form" variant="primary" loading={busy} disabled={!draft.trim() || busy}>
              Save
            </Button>
          </>
        }
      >
        <form id="rename-library-form" onSubmit={rename}>
          <Input ref={inputRef} label="Library name" value={draft} maxLength={120} onChange={(event) => setDraft(event.target.value)} required />
        </form>
      </Dialog>
      <Dialog
        open={dialog === "delete"}
        onClose={() => setDialog(null)}
        title={`Delete “${name}”?`}
        description="The stories in this library, your reading progress and notes for them are removed. Stories in other libraries stay."
        actions={
          <>
            <Button variant="ghost" onClick={() => setDialog(null)}>Cancel</Button>
            <Button variant="danger" loading={busy} disabled={busy} onClick={() => void remove()}>
              Delete library
            </Button>
          </>
        }
      />
    </>
  );
}

export default LibraryTitleMenu;
