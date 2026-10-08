import React from "react";
import { HideButton } from "./HideButton";
import type { BlocklistKind } from "../../types/organization";
import { termNames, type TermLike } from "./termNames";

interface TermHideListProps {
  kind: Extract<BlocklistKind, "tag" | "fandom" | "genre">;
  label: string;
  terms: TermLike[] | null | undefined;
}

/** Chips for tags, fandoms or genres, each with a one-click Hide. */
export const TermHideList: React.FC<TermHideListProps> = ({ kind, label, terms }) => {
  const names = termNames(terms);
  if (names.length === 0) return null;
  return (
    <div className="term-hide-list">
      <span className="term-hide-list__label">{label}</span>
      <ul>
        {names.map((name) => (
          <li key={name} className="term-hide-list__item">
            <span>{name}</span>
            <HideButton kind={kind} value={name} />
          </li>
        ))}
      </ul>
    </div>
  );
};
