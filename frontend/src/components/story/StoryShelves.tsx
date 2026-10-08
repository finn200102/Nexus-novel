import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { organizationService } from "../../services/organizationService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import type { Shelf } from "../../types/organization";
import { FilterChip } from "../ui";

/** Shelf chips for one library story: selected = on that shelf. */
const StoryShelves: React.FC<{ novelId: number }> = ({ novelId }) => {
  const { addToast } = useToast();
  const [shelves, setShelves] = useState<Shelf[] | null>(null);
  const [pending, setPending] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    organizationService.listShelves()
      .then((rows) => active && setShelves(rows))
      .catch(() => active && setShelves([]));
    return () => {
      active = false;
    };
  }, []);

  const toggle = async (shelf: Shelf, on: boolean) => {
    setPending(shelf.id);
    try {
      const updated = on
        ? await organizationService.addNovelToShelf(shelf.id, novelId)
        : await organizationService.removeNovelFromShelf(shelf.id, novelId);
      setShelves((current) => (current ?? []).map((item) => (item.id === shelf.id ? updated : item)));
    } catch (error) {
      addToast(getUserFacingError(error, "Could not update the shelf."), "error");
    } finally {
      setPending(null);
    }
  };

  return (
    <section className="story-section" aria-labelledby="story-shelves">
      <h2 id="story-shelves" className="story-section__title">Shelves</h2>
      {shelves === null ? (
        <p className="story-hint" role="status">Loading shelves…</p>
      ) : shelves.length === 0 ? (
        <p className="story-hint">You have no shelves yet. <Link to="/library" className="story-link">Create one in the Library</Link>.</p>
      ) : (
        <div className="story-chips" role="group" aria-label="Shelves for this story">
          {shelves.map((shelf) => (
            <FilterChip
              key={shelf.id}
              selected={shelf.novel_ids.includes(novelId)}
              disabled={pending === shelf.id}
              onChange={(on) => void toggle(shelf, on)}
            >
              {shelf.name}
            </FilterChip>
          ))}
        </div>
      )}
    </section>
  );
};

export default StoryShelves;
