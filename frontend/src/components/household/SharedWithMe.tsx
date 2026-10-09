import React, { useEffect, useState } from "react";
import "../../styles/household.css";
import { Badge, Button, Cover, ListRow } from "../ui";
import { householdService } from "../../services/householdService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import { useAuth } from "../../context/AuthContext";
import type { SharedShelfDetail, SharedShelfSummary } from "../../types/household";

/**
 * "Shared with me" in the Library: shelves other people on this instance share with you. Stories are
 * catalog links; open one and add it to your own library to read it. Renders nothing when empty.
 */
export const SharedWithMe: React.FC = () => {
  const { addToast } = useToast();
  const { user } = useAuth();
  const [shelves, setShelves] = useState<SharedShelfSummary[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SharedShelfDetail | null>(null);

  useEffect(() => {
    let active = true;
    householdService.sharedWithMe().then((rows) => active && setShelves(rows)).catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (openId == null) return;
    let active = true;
    setDetail(null);
    householdService
      .shelfStories(openId)
      .then((value) => active && setDetail(value))
      .catch((error: unknown) => active && addToast(getUserFacingError(error, "Could not open the shelf."), "error"));
    return () => {
      active = false;
    };
  }, [openId, addToast]);

  const leave = async (shelf: SharedShelfSummary, userId: number) => {
    try {
      await householdService.unshare(shelf.id, userId);
      setShelves((rows) => rows.filter((row) => row.id !== shelf.id));
      if (openId === shelf.id) setOpenId(null);
    } catch (error) {
      addToast(getUserFacingError(error, "Could not leave the shelf."), "error");
    }
  };

  const removeMine = async (shelfId: number, entryId: number) => {
    try {
      setDetail(await householdService.removeEntry(shelfId, entryId));
    } catch (error) {
      addToast(getUserFacingError(error, "Could not remove the story."), "error");
    }
  };

  if (shelves.length === 0) return null;

  return (
    <section className="shared-shelves" aria-labelledby="shared-shelves-title">
      <h2 id="shared-shelves-title" className="shared-shelves__title">Shared with me</h2>
      <ul className="shared-shelves__list">
        {shelves.map((shelf) => {
          const expanded = openId === shelf.id;
          return (
            <li key={shelf.id} className="shared-shelves__shelf">
              <div className="shared-shelves__head">
                <Button
                  variant="ghost"
                  aria-expanded={expanded}
                  aria-controls={`shared-shelf-${shelf.id}`}
                  onClick={() => setOpenId(expanded ? null : shelf.id)}
                >
                  {shelf.name}
                </Button>
                <span className="text-secondary text-sm">
                  from {shelf.owner.username} · {shelf.story_count} {shelf.story_count === 1 ? "story" : "stories"}
                </span>
                {shelf.permission === "collaborate" && <Badge tone="accent">Can add stories</Badge>}
                {user && (
                  <Button size="sm" variant="ghost" aria-label={`Leave ${shelf.name}`} onClick={() => void leave(shelf, user.id)}>
                    Leave
                  </Button>
                )}
              </div>
              {expanded && (
                <div id={`shared-shelf-${shelf.id}`} className="shared-shelves__stories">
                  {!detail ? (
                    <p role="status" className="text-secondary">Loading…</p>
                  ) : detail.stories.length === 0 ? (
                    <p className="text-secondary">No stories you can see on this shelf yet.</p>
                  ) : (
                    <ul aria-label={`Stories on ${shelf.name}`}>
                      {detail.stories.map((story) => (
                        <ListRow
                          as="li"
                          key={story.entry_id}
                          media={<Cover src={story.cover_url} title={story.title} author={story.author} size={48} />}
                          title={story.title}
                          to={story.metadata_id ? `/story/${story.metadata_id}` : undefined}
                          meta={
                            <>
                              {story.author && <span>{story.author}</span>}
                              {story.added_by && <span> · added by {story.added_by_me ? "you" : story.added_by}</span>}
                              {story.notes && <span className="shared-shelves__note"> · “{story.notes}”</span>}
                            </>
                          }
                          actions={
                            <>
                              {story.in_my_library ? <Badge tone="success">In your library</Badge> : null}
                              {story.added_by_me && detail.permission === "collaborate" && (
                                <Button size="sm" variant="ghost" aria-label={`Remove ${story.title} from ${shelf.name}`}
                                  onClick={() => void removeMine(shelf.id, story.entry_id)}>
                                  Remove
                                </Button>
                              )}
                            </>
                          }
                        />
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
};
