import React, { useEffect, useState } from "react";
import "../../styles/household.css";
import { Button, Dialog, Input, InputChip, Select, Switch } from "../ui";
import { householdService } from "../../services/householdService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import { CONTENT_RATING_LABELS, type ContentLimits, type ContentRating } from "../../types/household";

interface ContentLimitsDialogProps {
  user: { id: number; username: string; content_limits?: ContentLimits | null } | null;
  onClose: () => void;
  onSaved: (userId: number, limits: ContentLimits) => void;
}

const RATING_OPTIONS = [
  { value: "", label: "No rating limit" },
  ...(Object.keys(CONTENT_RATING_LABELS) as ContentRating[]).map((rating) => ({ value: rating, label: `Up to ${CONTENT_RATING_LABELS[rating]}` })),
];

/** Admin → Users: a household profile's maximum content rating, unrated handling and blocked tags. */
export const ContentLimitsDialog: React.FC<ContentLimitsDialogProps> = ({ user, onClose, onSaved }) => {
  const { addToast } = useToast();
  const [rating, setRating] = useState<ContentRating | "">("");
  const [hideUnrated, setHideUnrated] = useState(true);
  const [tags, setTags] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const current = user?.content_limits;
    setRating(current?.max_content_rating ?? "");
    setHideUnrated(current?.hide_unrated ?? true);
    setTags(current?.blocked_tags ?? []);
    setDraft("");
  }, [user]);

  if (!user) return null;

  const addTag = () => {
    const value = draft.trim();
    if (value && !tags.some((tag) => tag.toLowerCase() === value.toLowerCase())) setTags([...tags, value]);
    setDraft("");
  };

  const save = async () => {
    setSaving(true);
    try {
      const saved = await householdService.setLimits(user.id, {
        max_content_rating: rating || null,
        hide_unrated: hideUnrated,
        blocked_tags: tags,
      });
      onSaved(user.id, saved.content_limits);
      addToast(`Content limits saved for ${user.username}.`, "success");
      onClose();
    } catch (error) {
      addToast(getUserFacingError(error, "Could not save the content limits."), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Content limits for ${user.username}`}
      description="Stories above the rating or with a blocked tag are hidden from this profile everywhere: discovery, search, recommendations, shared shelves and imports."
      actions={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => void save()} disabled={saving}>Save limits</Button>
        </>
      }
    >
      <div className="content-limits">
        <Select
          label="Maximum rating"
          value={rating}
          options={RATING_OPTIONS}
          onChange={(event) => setRating(event.target.value as ContentRating | "")}
        />
        <Switch
          checked={hideUnrated}
          disabled={!rating}
          label="Hide stories without a rating"
          onChange={setHideUnrated}
        />
        <form
          className="content-limits__tags"
          onSubmit={(event) => {
            event.preventDefault();
            addTag();
          }}
        >
          <Input label="Blocked tag" value={draft} maxLength={60} placeholder="For example: Gore" onChange={(event) => setDraft(event.target.value)} />
          <Button type="submit" disabled={!draft.trim()}>Add tag</Button>
        </form>
        {tags.length > 0 && (
          <div className="content-limits__chips" aria-label="Blocked tags">
            {tags.map((tag) => (
              <InputChip key={tag} onRemove={() => setTags(tags.filter((item) => item !== tag))}>{tag}</InputChip>
            ))}
          </div>
        )}
      </div>
    </Dialog>
  );
};
