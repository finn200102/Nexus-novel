import React, { useRef, useState } from "react";
import { organizationService } from "../../services/organizationService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import { Button, Input, Sheet } from "../ui";
import type { Shelf } from "../../types/organization";

interface ShelfManagerProps {
  open: boolean;
  onClose: () => void;
  shelves: Shelf[];
  activeShelfId: number | null;
  onSelect: (shelfId: number | null) => void;
  onChanged: (shelves: Shelf[]) => void;
}

/**
 * "Shelves" sheet behind the Library page's Organize menu: create, rename and delete shelves.
 * Filtering by shelf stays in the Library filter row.
 */
export const ShelfManager: React.FC<ShelfManagerProps> = ({ open, onClose, shelves, activeShelfId, onSelect, onChanged }) => {
  const { addToast } = useToast();
  const [draft, setDraft] = useState("");
  const [renaming, setRenaming] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [confirming, setConfirming] = useState<number | null>(null);
  const newRef = useRef<HTMLInputElement | null>(null);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft.trim()) return;
    try {
      const created = await organizationService.createShelf(draft.trim());
      onChanged([...shelves, created]);
      setDraft("");
      onSelect(created.id);
    } catch (error) {
      addToast(getUserFacingError(error, "Could not create the shelf."), "error");
    }
  };

  const rename = async (shelf: Shelf) => {
    const next = renameValue.trim();
    setRenaming(null);
    if (!next || next === shelf.name) return;
    try {
      const updated = await organizationService.renameShelf(shelf.id, next);
      onChanged(shelves.map((item) => (item.id === shelf.id ? updated : item)));
    } catch (error) {
      addToast(getUserFacingError(error, "Could not rename the shelf."), "error");
    }
  };

  const remove = async (shelf: Shelf) => {
    setConfirming(null);
    try {
      await organizationService.deleteShelf(shelf.id);
      onChanged(shelves.filter((item) => item.id !== shelf.id));
      if (activeShelfId === shelf.id) onSelect(null);
    } catch (error) {
      addToast(getUserFacingError(error, "Could not delete the shelf."), "error");
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Shelves" initialFocus={newRef}>
      <div className="shelf-manager">
        <p className="text-secondary">Shelves group stories across your libraries. A story can be on several shelves.</p>
        <form className="shelf-manager__create" onSubmit={create}>
          <Input ref={newRef} label="New shelf" value={draft} maxLength={120} placeholder="For example: Rereads" onChange={(event) => setDraft(event.target.value)} />
          <Button type="submit" variant="primary" disabled={!draft.trim()}>Create shelf</Button>
        </form>
        {shelves.length === 0 ? (
          <p className="text-secondary">No shelves yet.</p>
        ) : (
          <ul className="shelf-manager__list" aria-label="Your shelves">
            {shelves.map((shelf) => (
              <li key={shelf.id} className="shelf-manager__row">
                {renaming === shelf.id ? (
                  <form className="shelf-manager__rename" onSubmit={(event) => { event.preventDefault(); void rename(shelf); }}>
                    <Input
                      label={`New name for ${shelf.name}`}
                      hideLabel
                      value={renameValue}
                      maxLength={120}
                      onChange={(event) => setRenameValue(event.target.value)}
                      autoFocus
                    />
                    <Button type="submit" size="sm" variant="primary">Save</Button>
                    <Button size="sm" variant="ghost" onClick={() => setRenaming(null)}>Cancel</Button>
                  </form>
                ) : confirming === shelf.id ? (
                  <div className="shelf-manager__confirm" role="group" aria-label={`Delete ${shelf.name}?`}>
                    <span>Delete “{shelf.name}”? The stories stay in your libraries.</span>
                    <Button size="sm" variant="danger" onClick={() => void remove(shelf)}>Delete</Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>Keep</Button>
                  </div>
                ) : (
                  <>
                    <span className="shelf-manager__name">
                      {shelf.name}
                      <span className="text-secondary text-sm"> · {shelf.novel_ids.length} {shelf.novel_ids.length === 1 ? "story" : "stories"}</span>
                    </span>
                    <Button size="sm" variant="ghost" aria-label={`Rename ${shelf.name}`} onClick={() => { setRenaming(shelf.id); setRenameValue(shelf.name); }}>
                      Rename
                    </Button>
                    <Button size="sm" variant="ghost" aria-label={`Delete ${shelf.name}`} onClick={() => setConfirming(shelf.id)}>
                      Delete
                    </Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Sheet>
  );
};
