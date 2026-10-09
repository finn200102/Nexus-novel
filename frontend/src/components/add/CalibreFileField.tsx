import React from "react";

interface Props {
  onFiles: (files: File[]) => void;
}

/** File picker for a Calibre library's metadata.db (one file). */
export const CalibreFileField: React.FC<Props> = ({ onFiles }) => (
  <div className="ui-field">
    <label className="ui-field__label" htmlFor="add-import-calibre">Calibre library (metadata.db)</label>
    <input
      id="add-import-calibre"
      className="add-import__file"
      type="file"
      accept=".db,application/x-sqlite3"
      aria-describedby="add-import-calibre-hint"
      onChange={(event) => onFiles(Array.from(event.target.files ?? []).slice(0, 1))}
    />
    <p className="ui-field__hint" id="add-import-calibre-hint">
      Pick metadata.db from your Calibre library folder. Tags, ratings and read state come with it; stories are matched by their source links.
    </p>
  </div>
);
