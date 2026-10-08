import React, { useState } from "react";
import type { AuthorNotesMode } from "./readerSettings";
import { splitAuthorNotes } from "./authorNotes";
import "./readerExtras.css";

interface ChapterBodyProps {
  content: string;
  authorNotes: AuthorNotesMode;
}

const NoteBlock: React.FC<{ paragraphs: string[]; mode: AuthorNotesMode; label: string }> = ({ paragraphs, mode, label }) => {
  const [open, setOpen] = useState(false);
  if (paragraphs.length === 0 || mode === "hidden") return null;
  if (mode === "shown") {
    return (
      <aside className="reader-author-note" aria-label="Author's note">
        {paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
      </aside>
    );
  }
  return (
    <div className="reader-author-note reader-author-note--collapsed">
      <button type="button" className="reader-author-note__toggle" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        {open ? "Hide" : "Show"} {label}
      </button>
      {open && paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
    </div>
  );
};

/** Renders chapter text as paragraphs, folding author's notes per the reader setting. */
const ChapterBody: React.FC<ChapterBodyProps> = ({ content, authorNotes }) => {
  const { head, body, tail } = splitAuthorNotes(content.split("\n"));
  return (
    <>
      <NoteBlock paragraphs={head} mode={authorNotes} label="author's note" />
      {body.map((paragraph, index) => (
        <p key={index}>{paragraph}</p>
      ))}
      <NoteBlock paragraphs={tail} mode={authorNotes} label="author's note" />
    </>
  );
};

export default ChapterBody;
