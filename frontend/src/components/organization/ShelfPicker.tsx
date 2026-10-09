import React, { useState } from "react";
import { organizationService } from "../../services/organizationService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import type { Shelf } from "../../types/organization";

interface ShelfPickerProps {
  novelId: number;
  shelves: Shelf[];
  onChanged?: (shelves: Shelf[]) => void;
}

/** Checkbox list that adds or removes one novel from each shelf. */
export const ShelfPicker: React.FC<ShelfPickerProps> = ({ novelId, shelves, onChanged }) => {
  const { addToast } = useToast();
  const [pending, setPending] = useState<number | null>(null);
  const [localShelves, setLocalShelves] = useState<Shelf[] | null>(null);
  const current = localShelves ?? shelves;
  const memberOf = (shelf: Shelf) => shelf.novel_ids.includes(novelId);

  const toggle = async (shelf: Shelf) => {
    setPending(shelf.id);
    try {
      const updated = memberOf(shelf)
        ? await organizationService.removeNovelFromShelf(shelf.id, novelId)
        : await organizationService.addNovelToShelf(shelf.id, novelId);
      const next = current.map((item) => (item.id === shelf.id ? updated : item));
      setLocalShelves(next);
      onChanged?.(next);
    } catch (error) {
      addToast(getUserFacingError(error, "Could not update the shelf."), "error");
    } finally {
      setPending(null);
    }
  };

  return (
    <details className="shelf-picker">
      <summary>Shelves{current.some(memberOf) ? ` · ${current.filter(memberOf).length}` : ""}</summary>
      {current.length === 0 ? (
        <p className="shelf-picker__empty">Create a shelf from Library › Organize › Shelves to file this story.</p>
      ) : (
        <ul>
          {current.map((shelf) => (
            <li key={shelf.id}>
              <label>
                <input
                  type="checkbox"
                  checked={memberOf(shelf)}
                  disabled={pending === shelf.id}
                  onChange={() => void toggle(shelf)}
                />
                {shelf.name}
              </label>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
};
