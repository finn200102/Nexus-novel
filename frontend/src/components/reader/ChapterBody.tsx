import React, { useId, useState } from "react";
import type { AuthorNotesMode } from "./readerSettings";
import { splitAuthorNotes } from "./authorNotes";
import "./readerExtras.css";

interface ChapterBodyProps {
  content: string;
  authorNotes: AuthorNotesMode;
}

/** Labelled, bordered author's note: shown in full, collapsed to two lines with "Show", or hidden. */
const NoteBlock: React.FC<{ paragraphs: string[]; mode: AuthorNotesMode; position: "start" | "end" }> = ({ paragraphs, mode, position }) => {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  if (paragraphs.length === 0 || mode === "hidden") return null;
  const expanded = mode === "shown" || open;
  return (
    <aside className={`reader-author-note reader-author-note--${position}`} aria-label="Author's note">
      <div className="reader-author-note__head">
        <strong>Author’s note</strong>
        {mode === "collapsed" && (
          <button type="button" className="reader-author-note__toggle" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen((value) => !value)}>
            {open ? "Show less" : "Show"}
          </button>
        )}
      </div>
      <div id={bodyId} className={expanded ? "reader-author-note__body" : "reader-author-note__body reader-author-note__body--clamped"}>
        {paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
      </div>
    </aside>
  );
};

/** Renders chapter text as paragraphs, folding author's notes per the reader setting. */
const ChapterBody: React.FC<ChapterBodyProps> = ({ content, authorNotes }) => {
  const { head, body, tail } = splitAuthorNotes(content.split("\n"));
  return (
    <>
      <NoteBlock paragraphs={head} mode={authorNotes} position="start" />
      {body.map((paragraph, index) => (paragraph.trim() ? <p key={index}>{paragraph}</p> : null))}
      <NoteBlock paragraphs={tail} mode={authorNotes} position="end" />
    </>
  );
};

export default ChapterBody;
