import React, { useEffect, useState } from "react";
import { ChipInput } from "../common/ChipInput";
import { MarkdownLite } from "../common/markdownLite";
import { organizationService } from "../../services/organizationService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";

interface PersonalPanelProps {
  novelId: number;
}

/** Private notes (Markdown subset), a 1-5 star rating and user tags for one novel. */
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

  useEffect(() => {
    let active = true;
    Promise.all([organizationService.getPersonal(novelId), organizationService.tagSuggestions("")])
      .then(([personal, known]) => {
        if (!active) return;
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
      const saved = await organizationService.savePersonal(novelId, {
        notes: notes.trim() ? notes : null,
        rating,
        user_tags: tags,
      });
      setDirty(false);
      setTags(saved.user_tags);
      addToast("Saved your notes.", "success");
    } catch (error) {
      addToast(getUserFacingError(error, "Could not save your notes."), "error");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="personal-panel__loading">Loading your notes…</p>;

  return (
    <section className="personal-panel" aria-labelledby={`personal-${novelId}`}>
      <h2 id={`personal-${novelId}`}>Your notes</h2>
      <p className="personal-panel__hint">Only you can see this. Notes support **bold**, *italic*, `code` and - lists.</p>

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
            ★
          </button>
        ))}
        <span>{rating ? `${rating}/5` : "Not rated"}</span>
      </div>

      <div className="personal-panel__notes">
        <div className="personal-panel__notes-head">
          <label htmlFor={`notes-${novelId}`}>Notes</label>
          <button type="button" onClick={() => setPreview((value) => !value)} aria-pressed={preview}>
            {preview ? "Edit" : "Preview"}
          </button>
        </div>
        {preview ? (
          <div className="personal-panel__preview" aria-label="Notes preview">
            {notes.trim() ? <MarkdownLite source={notes} /> : <p>Nothing written yet.</p>}
          </div>
        ) : (
          <textarea
            id={`notes-${novelId}`}
            value={notes}
            maxLength={20000}
            rows={6}
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

      <button type="button" className="personal-panel__save" onClick={() => void save()} disabled={saving || !dirty}>
        {saving ? "Saving…" : "Save notes"}
      </button>
    </section>
  );
};
