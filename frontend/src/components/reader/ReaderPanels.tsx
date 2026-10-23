import React, { useEffect, useRef, useState } from "react";
import { Bookmark, StickyNote, Trash2 } from "lucide-react";
import { Button, Dialog, IconButton, Sheet, Switch, TextArea } from "../ui";
import { READER_SHORTCUTS } from "../../hooks/useReaderShortcuts";

import type { ChapterRecapResponse, ReadingAnnotationResponse } from "../../generated/api";
// Panels need presentation fields only; ownership IDs and audit dates stay in
// the complete wire response returned by chapterService.
export type ReadingAnnotation = Pick<ReadingAnnotationResponse,
  "id" | "chapter_number" | "annotation_type" | "position" | "percent" | "quote" | "note" |
  "block_id" | "text_offset" | "text_quote" | "quote_prefix" | "quote_suffix" | "locator_content_version" | "locator_variant"> & Partial<Pick<ReadingAnnotationResponse,"chapter_key"|"archived"|"identity_unresolved"|"original_chapter_number">>;

/** "Add note" dialog (replaces window.prompt). */
export function NoteDialog({ open, quote, onClose, onSave }: { open: boolean; quote: string; onClose: () => void; onSave: (note: string) => void }) {
  const [note, setNote] = useState("");
  const fieldRef = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => { if (open) setNote(""); }, [open]);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add note"
      description={quote ? `On “${quote.length > 120 ? `${quote.slice(0, 120)}…` : quote}”` : "Saved at your current place in this chapter. Only you can see it."}
      initialFocus={fieldRef}
      actions={(
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => onSave(note.trim())}>Save note</Button>
        </>
      )}
    >
      <TextArea ref={fieldRef} label="Note" hint="Optional" rows={4} value={note} onChange={(event) => setNote(event.target.value)} />
    </Dialog>
  );
}

/** Bookmarks and notes for this story; jump to one or delete it. */
export function AnnotationsSheet({ open, onClose, annotations, chapterNumber, chapterKey, onJump, onDelete, onViewVersion, onEdit }: {
  open: boolean;
  onClose: () => void;
  annotations: ReadingAnnotation[];
  chapterNumber: number;
  chapterKey?: string;
  onJump: (annotation: ReadingAnnotation) => void;
  onDelete: (id: number) => void;
  onViewVersion?: (annotation: ReadingAnnotation) => void;
  onEdit?: (annotation: ReadingAnnotation, note: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState<ReadingAnnotation | null>(null);
  const [editNote, setEditNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState("");
  useEffect(() => { setEditing(null); setEditNote(""); setEditError(""); }, [open, chapterKey, chapterNumber]);
  useEffect(() => { if (editing && !annotations.some(item => item.id === editing.id && item.chapter_key === editing.chapter_key)) { setEditing(null); setEditNote(""); } }, [annotations, editing]);
  const saveEdit = async () => {
    if (!editing || !onEdit || saving) return;
    setSaving(true); setEditError("");
    try { await onEdit(editing, editNote.trim()); setEditing(null); }
    catch { setEditError("The note could not be saved. Refresh the chapter and try again."); }
    finally { setSaving(false); }
  };
  const belongsHere=(annotation:ReadingAnnotation)=>chapterKey ? annotation.chapter_key===chapterKey : annotation.chapter_number===chapterNumber;
  const here = annotations.filter(belongsHere);
  const elsewhere = annotations.filter(annotation=>!belongsHere(annotation));
  const row = (annotation: ReadingAnnotation) => {
    const text = annotation.note || annotation.quote || `At ${Math.round(annotation.percent)}%`;
    const kind = annotation.annotation_type === "bookmark" ? "Bookmark" : "Note";
    return (
      <li key={annotation.id} className="reader-annotations__row">
        <button type="button" className="reader-annotations__jump" disabled={annotation.identity_unresolved || annotation.chapter_number == null} onClick={() => onJump(annotation)}>
          {annotation.annotation_type === "bookmark" ? <Bookmark aria-hidden="true" size={16} /> : <StickyNote aria-hidden="true" size={16} />}
          <span>
            <span className="visually-hidden">{kind}: </span>{text}
            <span className="reader-annotations__where">{annotation.chapter_number == null ? "Original chapter needs identity review" : `Chapter ${annotation.chapter_number}`} · {Math.round(annotation.percent)}%</span>
          </span>
        </button>
        {annotation.locator_content_version && annotation.chapter_number != null && !annotation.identity_unresolved && onViewVersion && <Button variant="ghost" size="sm" onClick={() => onViewVersion(annotation)}>Saved text</Button>}
        {onEdit && belongsHere(annotation) && !annotation.identity_unresolved && !annotation.archived && annotation.chapter_number != null && <Button variant="ghost" size="sm" onClick={() => { setEditing(annotation); setEditNote(annotation.note || ""); setEditError(""); }}>Edit note</Button>}
        {onEdit && !belongsHere(annotation) && !annotation.identity_unresolved && !annotation.archived && annotation.chapter_number != null && <Button variant="ghost" size="sm" onClick={() => onJump(annotation)}>Open chapter to edit</Button>}
        <IconButton label={`Delete ${kind.toLowerCase()}: ${text.slice(0, 40)}`} icon={<Trash2 />} tooltip="none" size="sm" onClick={() => onDelete(annotation.id)} />
      </li>
    );
  };
  return (
    <><Sheet open={open} onClose={onClose} title="Bookmarks and notes" closeLabel="Close bookmarks and notes">
      {annotations.length === 0 && <p className="text-muted">No bookmarks or notes yet. Press B or use the bookmark button to mark your place.</p>}
      {here.length > 0 && (<><h3 className="reader-annotations__heading">This chapter</h3><ul className="reader-annotations">{here.map(row)}</ul></>)}
      {elsewhere.length > 0 && (<><h3 className="reader-annotations__heading">Other chapters</h3><ul className="reader-annotations">{elsewhere.map(row)}</ul></>)}
    </Sheet>
    <Dialog open={editing !== null} onClose={() => { if (!saving) setEditing(null); }} title="Edit note" actions={<><Button variant="ghost" disabled={saving} onClick={() => setEditing(null)}>Cancel</Button><Button variant="primary" disabled={saving} onClick={() => void saveEdit()}>{saving ? "Saving…" : "Save note"}</Button></>}>
      {editing?.quote && <blockquote>{editing.quote}</blockquote>}
      <TextArea label="Note" rows={4} maxLength={20000} value={editNote} onChange={event => setEditNote(event.target.value)} />
      {editError && <p role="alert">{editError}</p>}
    </Dialog></>
  );
}

/** Keyboard shortcuts dialog with the single-key switch (WCAG 2.1.4). */
export function ShortcutsDialog({ open, onClose, enabled, onEnabled }: { open: boolean; onClose: () => void; enabled: boolean; onEnabled: (v: boolean) => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Keyboard shortcuts" actions={<Button variant="primary" onClick={onClose}>Done</Button>}>
      <Switch label="Single-key shortcuts" checked={enabled} onChange={onEnabled} />
      <p className="text-sm text-muted">When off, only the arrow keys, Space and Esc work. Shortcuts never fire while you type in a field.</p>
      <dl className="reader-shortcuts">
        {READER_SHORTCUTS.map((shortcut) => (
          <div key={shortcut.action} className={shortcut.singleKey && !enabled && !shortcut.keys[0].startsWith("←") && !shortcut.keys[0].startsWith("→") ? "reader-shortcuts__off" : undefined}>
            <dt>{shortcut.keys.map((key, i) => <React.Fragment key={key}>{i > 0 && " or "}<kbd>{key}</kbd></React.Fragment>)}</dt>
            <dd>{shortcut.action}</dd>
          </div>
        ))}
      </dl>
    </Dialog>
  );
}

export type RecapData = Pick<ChapterRecapResponse, "summary" | "spoiler_boundary_chapter" | "chapters">;

/** Spoiler-safe recap plus reading stats and update cadence (until they move to the story page, D9). */
export function RecapSheet({ open, onClose, recap, loading, history, hiatus }: {
  open: boolean;
  onClose: () => void;
  recap: RecapData | null;
  loading: boolean;
  history: { chapters_touched: number; active_days: number; current_streak_days: number } | null;
  hiatus: { state: string; reason: string } | null;
}) {
  return (
    <Sheet open={open} onClose={onClose} title="Recap so far" closeLabel="Close recap">
      {loading && <p className="text-muted">Writing a recap…</p>}
      {recap && (
        <section className="reader-recap">
          <h3>{recap.spoiler_boundary_chapter == null ? "No verified chapter evidence" : `Up to chapter ${recap.spoiler_boundary_chapter}`}</h3>
          <p>{recap.summary}</p>
          {recap.spoiler_boundary_chapter != null && recap.chapters.length > 0 && <ul>{recap.chapters.slice(-5).map((item) => <li key={item.number}>{item.number}. {item.title}</li>)}</ul>}
        </section>
      )}
      {!loading && !recap && <p className="text-muted">No recap available right now.</p>}
      <section className="reader-recap">
        <h3>Your reading</h3>
        {history
          ? <p>{history.chapters_touched} chapters read · {history.active_days} active days · {history.current_streak_days}-day streak</p>
          : <p className="text-muted">Reading stats appear after a few days of reading.</p>}
        {hiatus && (
          <p>
            <strong>{hiatus.state === "likely_hiatus" ? "Likely on hiatus" : hiatus.state === "active" ? "Updates regularly" : "Update pattern not known yet"}</strong>
            {" · "}<span className="text-muted">{hiatus.reason}</span>
          </p>
        )}
      </section>
    </Sheet>
  );
}
