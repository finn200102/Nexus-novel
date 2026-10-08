import React, { useState } from "react";
import { organizationService } from "../../services/organizationService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import type { Shelf } from "../../types/organization";

interface ShelfBarProps {
  shelves: Shelf[];
  activeShelfId: number | null;
  onSelect: (shelfId: number | null) => void;
  onChanged: (shelves: Shelf[]) => void;
}

/** Shelf filter chips for the Library page, with create, rename and delete. */
export const ShelfBar: React.FC<ShelfBarProps> = ({ shelves, activeShelfId, onSelect, onChanged }) => {
  const { addToast } = useToast();
  const [draft, setDraft] = useState("");
  const [renaming, setRenaming] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");

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
    if (!window.confirm(`Delete the shelf "${shelf.name}"? Novels stay in your libraries.`)) return;
    try {
      await organizationService.deleteShelf(shelf.id);
      onChanged(shelves.filter((item) => item.id !== shelf.id));
      if (activeShelfId === shelf.id) onSelect(null);
    } catch (error) {
      addToast(getUserFacingError(error, "Could not delete the shelf."), "error");
    }
  };

  return (
    <div className="shelf-bar" aria-label="Shelves">
      <div className="shelf-bar__chips">
        <button type="button" className={activeShelfId === null ? "is-active" : ""} onClick={() => onSelect(null)}>
          All shelves
        </button>
        {shelves.map((shelf) =>
          renaming === shelf.id ? (
            <form key={shelf.id} className="shelf-bar__rename" onSubmit={(event) => { event.preventDefault(); void rename(shelf); }}>
              <input
                aria-label={`New name for ${shelf.name}`}
                value={renameValue}
                maxLength={120}
                onChange={(event) => setRenameValue(event.target.value)}
                autoFocus
              />
              <button type="submit">Save</button>
            </form>
          ) : (
            <span key={shelf.id} className="shelf-bar__shelf">
              <button
                type="button"
                className={activeShelfId === shelf.id ? "is-active" : ""}
                aria-pressed={activeShelfId === shelf.id}
                onClick={() => onSelect(shelf.id)}
              >
                {shelf.name} <small>{shelf.novel_ids.length}</small>
              </button>
              <button
                type="button"
                aria-label={`Rename ${shelf.name}`}
                onClick={() => {
                  setRenaming(shelf.id);
                  setRenameValue(shelf.name);
                }}
              >
                Rename
              </button>
              <button type="button" aria-label={`Delete ${shelf.name}`} onClick={() => void remove(shelf)}>
                Delete
              </button>
            </span>
          ),
        )}
      </div>
      <form className="shelf-bar__create" onSubmit={create}>
        <input
          aria-label="New shelf name"
          value={draft}
          maxLength={120}
          placeholder="New shelf"
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" disabled={!draft.trim()}>Create shelf</button>
      </form>
    </div>
  );
};
