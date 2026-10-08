import React from "react";

interface ReasonListProps {
  reasons?: string[] | null;
  /** Use spans so the list can sit inside a button-based card. */
  inline?: boolean;
}

/** Short "why this" sentences shown under a recommended or similar story. */
export const ReasonList: React.FC<ReasonListProps> = ({ reasons, inline = false }) => {
  if (!reasons || reasons.length === 0) return null;
  if (inline) {
    return (
      <span className="reason-list reason-list--inline" aria-label="Why this">
        {reasons.map((reason) => (
          <span key={reason} className="reason-list__item">{reason}</span>
        ))}
      </span>
    );
  }
  return (
    <ul className="reason-list" aria-label="Why this">
      {reasons.map((reason) => (
        <li key={reason}>{reason}</li>
      ))}
    </ul>
  );
};
