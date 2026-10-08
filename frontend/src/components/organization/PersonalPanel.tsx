import React, { useEffect, useRef, useState } from "react";
import { ChipInput } from "../common/ChipInput";
import { MarkdownLite } from "../common/markdownLite";
import { organizationService } from "../../services/organizationService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import { Star } from "lucide-react";
import { Button, TextArea } from "../ui";

interface PersonalPanelProps {
  novelId: number;
}

/** Private notes (plain text; a Markdown subset is accepted), a 1-5 star rating and user tags for one novel. */
export const PersonalPanel: React.FC<PersonalPanelProps> = ({ novelId }) => {
  const { addToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [notes, setNotes] = useState("");
  const [rating, setRating] = useState<number | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  // What the server last returned, so a save sends only what changed.
  const stored = useRef<{ notes: string | null; rating: number | null; tags: string[] }>({ notes: null, rating: null, tags: [] });

  useEffect(() => {
    let active = true;
    Promise.all([organizationService.getPersonal(novelId), organizationService.tagSuggestions("")])
      .then(([personal, known]) => {
        if (!active) return;
        stored.current = { notes: personal.notes, rating: personal.rating, tags: personal.user_tags };
        setNotes(personal.notes ?? "");
        setRating(personal.rating);
        setTags(personal.user_tags);
        setSuggestions(known);
        setDirty(false);
      })
      .catch((error) => active && addToast(getUserFacingError(error, "Could not load your notes."), "error"))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [novelId, addToast]);

  const save = async () => {
    setSaving(true);
    try {
      const changes: { notes?: string | null; rating?: number | null; user_tags?: string[] } = {};
      const nextNotes = notes.trim() ? notes : null;
      if (nextNotes !== stored.current.notes) changes.notes = nextNotes;
      if (rating !== stored.current.rating) changes.rating = rating;
      if (tags.join("\n") !== stored.current.tags.join("\n")) changes.user_tags = tags;
      if (Object.keys(changes).length > 0) {
        const saved = await organizationService.savePersonal(novelId, changes);
        stored.current = { notes: saved.notes, rating: saved.rating, tags: saved.user_tags };
        setTags(saved.user_tags);
      }
      setDirty(false);
      addToast("Saved your notes.", "success");
    } catch (error) {
      addToast(getUserFacingError(error, "Could not save your notes."), "error");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="personal-panel__loading" role="status">Loading your notes…</p>;

  return (
    <section className="personal-panel" aria-labelledby={`personal-${novelId}`}>
      <h2 id={`personal-${novelId}`}>Your notes</h2>
      <p className="personal-panel__hint">Only you can see this.</p>

      <div className="personal-panel__rating" role="group" aria-label="Your rating">
        {[1, 2, 3, 4, 5].map((stars) => (
          <button
            key={stars}
            type="button"
            aria-label={`Rate ${stars} ${stars === 1 ? "star" : "stars"}`}
            aria-pressed={rating !== null && rating >= stars}
            className={rating !== null && rating >= stars ? "is-on" : ""}
            onClick={() => {
              setRating(rating === stars ? null : stars);
              setDirty(true);
            }}
          >
            <Star size={22} aria-hidden="true" fill={rating !== null && rating >= stars ? "currentColor" : "none"} />
          </button>
        ))}
        <span>{rating ? `${rating}/5` : "Not rated"}</span>
      </div>

      <div className="personal-panel__notes">
        <div className="personal-panel__notes-head">
          <span className="personal-panel__notes-label" aria-hidden="true">Private notes</span>
          <Button size="sm" variant="ghost" onClick={() => setPreview((value) => !value)} aria-pressed={preview}>
            {preview ? "Edit" : "Preview"}
          </Button>
        </div>
        {preview ? (
          <div className="personal-panel__preview" aria-label="Notes preview">
            {notes.trim() ? <MarkdownLite source={notes} /> : <p>Nothing written yet.</p>}
          </div>
        ) : (
          <TextArea
            id={`notes-${novelId}`}
            label="Private notes"
            hideLabel
            value={notes}
            maxLength={20000}
            rows={6}
            hint="Plain text is fine. **bold**, *italic* and - lists also work."
            onChange={(event) => {
              setNotes(event.target.value);
              setDirty(true);
            }}
          />
        )}
      </div>

      <ChipInput
        label="Your tags"
        values={tags}
        suggestions={suggestions}
        placeholder="Add a tag, then Enter"
        onChange={(values) => {
          setTags(values);
          setDirty(true);
        }}
      />

      <Button className="personal-panel__save" onClick={() => void save()} disabled={saving || !dirty} loading={saving}>
        Save notes
      </Button>
    </section>
  );
};
