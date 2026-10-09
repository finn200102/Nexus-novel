import React, { useId, useState } from "react";
import { X } from "lucide-react";
import "../../styles/chip-input.css";

type ChipInputProps = {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  suggestions?: string[];
  tone?: "include" | "exclude";
  onDraftChange?: (draft: string) => void;
};

/**
 * Multi-value text input. Enter or a comma turns the draft into a chip;
 * Backspace on an empty draft removes the last chip.
 */
export const ChipInput: React.FC<ChipInputProps> = ({
  label,
  values,
  onChange,
  placeholder,
  suggestions,
  tone = "include",
  onDraftChange,
}) => {
  const [draft, setDraft] = useState("");
  const inputId = useId();
  const labelId = `${inputId}-label`;
  const listId = `${inputId}-options`;

  const updateDraft = (value: string) => {
    setDraft(value);
    onDraftChange?.(value);
  };

  const commit = (raw: string) => {
    const pieces = raw.split(",").map((piece) => piece.trim()).filter(Boolean);
    if (pieces.length === 0) {
      updateDraft("");
      return;
    }
    const next = [...values];
    for (const piece of pieces) {
      if (!next.some((value) => value.toLowerCase() === piece.toLowerCase())) next.push(piece);
    }
    onChange(next);
    updateDraft("");
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commit(draft);
    } else if (event.key === "Backspace" && !draft && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  };

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const value = event.target.value;
    if (value.includes(",")) {
      commit(value);
    } else {
      updateDraft(value);
    }
  };

  return (
    <div className={`discover-chip-field discover-chip-field--${tone}`}>
      <span id={labelId} className="discover-chip-field__label">{label}</span>
      <div className="discover-chip-field__box">
        {values.map((value) => (
          <span key={value} className="discover-chip">
            {value}
            <button
              type="button"
              aria-label={`Remove ${value}`}
              onClick={() => onChange(values.filter((item) => item !== value))}
            >
              <X size={12} aria-hidden="true" />
            </button>
          </span>
        ))}
        <input
          id={inputId}
          aria-labelledby={labelId}
          value={draft}
          list={suggestions && suggestions.length > 0 ? listId : undefined}
          placeholder={values.length === 0 ? placeholder : undefined}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onBlur={() => {
            if (draft.trim()) commit(draft);
          }}
        />
      </div>
      {suggestions && suggestions.length > 0 && (
        <datalist id={listId}>
          {suggestions.map((suggestion) => <option key={suggestion} value={suggestion} />)}
        </datalist>
      )}
    </div>
  );
};

export default ChipInput;
