import React, { useEffect, useState } from "react";
import "../../styles/household.css";
import { Button, Dialog, SegmentedControl, Select, Switch } from "../ui";
import { householdService } from "../../services/householdService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import type { SharePermission, ShareTarget, ShelfShares } from "../../types/household";

interface ShareShelfDialogProps {
  shelf: { id: number; name: string } | null;
  onClose: () => void;
  /** Called with the new number of people the shelf is shared with. */
  onChanged?: (shelfId: number, shareCount: number) => void;
}

const PERMISSIONS = [
  { value: "view" as const, label: "Can view" },
  { value: "collaborate" as const, label: "Can add stories" },
];

/**
 * Share a shelf with other people on this instance. They see the stories as catalog links (and your
 * notes if you allow it), never your downloaded chapters: they add a story to their own library.
 */
export const ShareShelfDialog: React.FC<ShareShelfDialogProps> = ({ shelf, onClose, onChanged }) => {
  const { addToast } = useToast();
  const [targets, setTargets] = useState<ShareTarget[]>([]);
  const [state, setState] = useState<ShelfShares | null>(null);
  const [userId, setUserId] = useState("");
  const [permission, setPermission] = useState<SharePermission>("view");
  const [busy, setBusy] = useState(false);
  const shelfId = shelf?.id ?? null;

  useEffect(() => {
    if (shelfId == null) return;
    let active = true;
    setState(null);
    setUserId("");
    Promise.all([householdService.shareTargets(), householdService.shares(shelfId)])
      .then(([people, shares]) => {
        if (!active) return;
        setTargets(people);
        setState(shares);
      })
      .catch((error: unknown) => active && addToast(getUserFacingError(error, "Could not load sharing."), "error"));
    return () => {
      active = false;
    };
  }, [shelfId, addToast]);

  const apply = (next: ShelfShares) => {
    setState(next);
    onChanged?.(next.shelf_id, next.shares.length);
  };

  const run = async (action: () => Promise<void>, failure: string) => {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      addToast(getUserFacingError(error, failure), "error");
    } finally {
      setBusy(false);
    }
  };

  if (!shelf) return null;
  const sharedIds = new Set(state?.shares.map((share) => share.user_id));
  const available = targets.filter((target) => !sharedIds.has(target.id));

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Share “${shelf.name}”`}
      description="People you share with see these stories and can add them to their own library. Your downloaded chapters, EPUBs and audio stay yours."
      actions={<Button onClick={onClose}>Done</Button>}
    >
      <div className="share-shelf">
        <form
          className="share-shelf__add"
          onSubmit={(event) => {
            event.preventDefault();
            if (!userId) return;
            void run(async () => {
              apply(await householdService.share(shelf.id, Number(userId), permission));
              setUserId("");
            }, "Could not share the shelf.");
          }}
        >
          <Select
            label="Person"
            value={userId}
            onChange={(event) => setUserId(event.target.value)}
            options={[
              { value: "", label: available.length ? "Choose someone" : "Nobody else to share with" },
              ...available.map((target) => ({ value: String(target.id), label: target.username })),
            ]}
          />
          <SegmentedControl label="Permission" options={PERMISSIONS} value={permission} onChange={setPermission} />
          <Button type="submit" variant="primary" disabled={!userId || busy}>Share</Button>
        </form>

        {state && (
          <>
            {state.shares.length === 0 ? (
              <p className="text-secondary">Not shared with anyone yet.</p>
            ) : (
              <ul className="share-shelf__list" aria-label="Shared with">
                {state.shares.map((share) => (
                  <li key={share.user_id} className="share-shelf__row">
                    <span className="share-shelf__name">{share.username}</span>
                    <Select
                      label={`Permission for ${share.username}`}
                      hideLabel
                      value={share.permission}
                      disabled={busy}
                      options={PERMISSIONS}
                      onChange={(event) =>
                        void run(async () => apply(await householdService.share(shelf.id, share.user_id, event.target.value as SharePermission)),
                          "Could not change the permission.")}
                    />
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      aria-label={`Stop sharing with ${share.username}`}
                      onClick={() =>
                        void run(async () => {
                          await householdService.unshare(shelf.id, share.user_id);
                          apply({ ...state, shares: state.shares.filter((item) => item.user_id !== share.user_id) });
                        }, "Could not stop sharing.")}
                    >
                      Remove
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <Switch
              checked={state.share_notes}
              disabled={busy}
              label="Show my notes on these stories"
              onChange={(checked) =>
                void run(async () => {
                  await householdService.setShareNotes(shelf.id, checked);
                  setState({ ...state, share_notes: checked });
                }, "Could not change note sharing.")}
            />
          </>
        )}
      </div>
    </Dialog>
  );
};
