import React from "react";
import type { AuthorNotesMode, ReaderLayout } from "./readerSettings";

interface ReaderPrefsControlsProps {
  authorNotes: AuthorNotesMode;
  onAuthorNotes: (mode: AuthorNotesMode) => void;
  layout: ReaderLayout;
  onLayout: (layout: ReaderLayout) => void;
  hasStoryOverride: boolean;
  onUseForAll: () => void;
  onResetToGlobal: () => void;
}

/** Inspector controls for author's notes, page layout and per-story typography scope. */
const ReaderPrefsControls: React.FC<ReaderPrefsControlsProps> = ({
  authorNotes,
  onAuthorNotes,
  layout,
  onLayout,
  hasStoryOverride,
  onUseForAll,
  onResetToGlobal,
}) => (
  <section className="reader-inspector__section" aria-label="Reading layout">
    <header><strong>Layout</strong></header>
    <label>Author&apos;s notes
      <select aria-label="Author's notes" value={authorNotes} onChange={(event) => onAuthorNotes(event.target.value as AuthorNotesMode)}>
        <option value="collapsed">Collapsed</option>
        <option value="shown">Shown</option>
        <option value="hidden">Hidden</option>
      </select>
    </label>
    <label>Reading mode
      <select aria-label="Reading mode" value={layout} onChange={(event) => onLayout(event.target.value as ReaderLayout)}>
        <option value="scroll">Scroll</option>
        <option value="paged">Paged</option>
      </select>
    </label>
    <small>{hasStoryOverride ? "These text settings are saved for this story only." : "Text settings follow your global defaults."}</small>
    <div className="reader-theme-controls">
      {hasStoryOverride ? (
        <>
          <button type="button" onClick={onUseForAll}>Use for all stories</button>
          <button type="button" onClick={onResetToGlobal}>Reset to global</button>
        </>
      ) : null}
    </div>
  </section>
);

export default ReaderPrefsControls;
