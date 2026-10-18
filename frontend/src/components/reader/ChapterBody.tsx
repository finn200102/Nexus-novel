import React, { memo, useId, useState } from "react";
import type { AuthorNotesMode } from "./readerSettings";
import { splitAuthorNotes, isAuthorNoteParagraph } from "./authorNotes";
import "./readerExtras.css";
import type { ChapterDocument, ChapterBlock } from "./chapterDocument";
import { ReaderIllustrations } from "./ReaderIllustrations";

interface ChapterBodyProps {
  content: string;
  authorNotes: AuthorNotesMode;
  document?: ChapterDocument;
}

// Replacing identical innerHTML would discard live selections and DOM ranges
// whenever progress or toolbar state causes the reader to render again.
const RichBlock = memo(({ block }: { block: ChapterBlock }) => <section data-block-id={block.id}
  className="reader-rich-block" dangerouslySetInnerHTML={{ __html: block.html }} />,
  (before, after) => before.block.id === after.block.id && before.block.html === after.block.html);

/** Labelled, bordered author's note: shown in full, collapsed to two lines with "Show", or hidden. */
const NoteBlock: React.FC<{ paragraphs?: { text: string; id?: string }[]; blocks?: ChapterBlock[]; mode: AuthorNotesMode; position: "start" | "end" | "inline" }> = ({ paragraphs = [], blocks = [], mode, position }) => {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  if ((!paragraphs.length && !blocks.length) || mode === "hidden") return null;
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
        {paragraphs.map((paragraph, index) => <p key={index} data-block-id={paragraph.id}>{paragraph.text}</p>)}
        {blocks.map(block => <RichBlock key={block.id} block={block} />)}
      </div>
    </aside>
  );
};

/** Renders chapter text as paragraphs, folding author's notes per the reader setting. */
const ChapterBody: React.FC<ChapterBodyProps> = ({ content, authorNotes, document }) => {
  if (document?.source_format === "html" && document.schema_version === 1) {
    const notes = new Set(document.blocks.filter(block => block.role === "author_note").map(block => block.id));
    // Older rich documents can still identify a run of explicit note markers
    // at either end; an ordinary sentence in the middle stays story text.
    for (const ordered of [document.blocks, [...document.blocks].reverse()]) {
      for (const block of ordered) {
        if (!isAuthorNoteParagraph(block.text) && !notes.has(block.id)) break;
        notes.add(block.id);
      }
    }
    const groups: { note: boolean; blocks: ChapterBlock[]; index: number }[] = [];
    document.blocks.forEach((block, index) => {
      const note = notes.has(block.id), previous = groups[groups.length - 1];
      if (note && previous?.note) previous.blocks.push(block);
      else groups.push({ note, blocks: [block], index });
    });
    return <ReaderIllustrations key={document.content_version}>{groups.map(group => group.note
      ? <NoteBlock key={group.blocks[0].id} blocks={group.blocks} mode={authorNotes} position={group.index === 0 ? "start" : group.index + group.blocks.length === document.blocks.length ? "end" : "inline"} />
      : <RichBlock key={group.blocks[0].id} block={group.blocks[0]} />)}</ReaderIllustrations>;
  }
  const { head, body, tail } = splitAuthorNotes(content.split("\n"));
  let blockIndex = 0;
  const anchored = (paragraphs: string[]) => paragraphs.filter(paragraph => paragraph.trim()).map(text => {
    const index = blockIndex++;
    return { text, id: document?.blocks[index]?.id || `legacy-p-${index}` };
  });
  const headRows = anchored(head), bodyRows = anchored(body), tailRows = anchored(tail);
  return (
    <>
      <NoteBlock paragraphs={headRows} mode={authorNotes} position="start" />
      {bodyRows.map((paragraph, index) => <p key={index} data-block-id={paragraph.id}>{paragraph.text}</p>)}
      <NoteBlock paragraphs={tailRows} mode={authorNotes} position="end" />
    </>
  );
};

export default ChapterBody;
